# P5.1 Experiment Plan: Late-Season Marginal Wheat Crop Substitution (T1)

## 1. Executive Summary & Objective

Phase **P5.1** will implement the validated Late-Wheat Crop Substitution (T1) policy in the production agent codebase under a strictly isolated, zero-overhead feature toggle:
`P51_T1_MARGINAL_WHEAT_SUBSTITUTION_ENABLED`.

The objective is to capture the verified **+$655.25 / \text{game}$** surplus on Days 21–23 by substituting genuine surplus wheat with two 3-day carrot rotations, while preserving 100% feed security and strict bit-for-bit baseline equivalence when disabled.

---

## 2. Feature Flag & Architectural Invariants

### 2.1 Flag Specification in `agent/config.py`
```python
P51_T1_MARGINAL_WHEAT_SUBSTITUTION_ENABLED: bool = False

def set_p51_t1_marginal_wheat_substitution_enabled(enabled: bool) -> None:
    global P51_T1_MARGINAL_WHEAT_SUBSTITUTION_ENABLED
    P51_T1_MARGINAL_WHEAT_SUBSTITUTION_ENABLED = bool(enabled)
```
- **Default State**: `False`.
- **Bit-for-Bit Control Invariant**: When disabled (`False`), the agent produces bit-for-bit identical actions to baseline commit `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e`.
- **Zero Scope Creep**: Excludes T2 fertilizer reallocation, T3 livestock, T4 idle slack harvesting, and SW land expansion.

---

## 3. Production Implementation Architecture

The change is localized to `agent/strategy/macro_planner.py` within the core crop planning sequence:

### 3.1 Decision Logic Integration (`macro_planner.py`)
1. **At Days 21–23 (Cycle 1 Insertion)**:
   - When evaluating empty tiles that would otherwise be assigned to wheat up to `quadrant_wheat_target`:
   - Query the Time-Indexed Dynamic Feed Ledger:
     ```python
     is_safe, min_buf = simulate_feed_ledger(ctx, exclude_tile=tile_pos)
     ```
   - If `is_safe` and `min_buf >= 1.0 * herd_size` and `hour <= 17`:
     - Assign `CARROT` to `plant_queue`.
     - Allocate $20 seed budget to `buy_seed["CARROT"]` (instead of $10 to `buy_seed["WHEAT"]`).
     - Tag tile in memory as `t1_cycle1_tile`.
2. **At Days 24–26 (Cycle 2 Insertion)**:
   - When `t1_cycle1_tile` matures at age 3 and is harvested in the morning:
   - The tile becomes empty.
   - The planner recognizes the completed Cycle 1 and queues Cycle 2:
     - Assign `CARROT` to `plant_queue`.
     - Allocate $20 seed budget to `buy_seed["CARROT"]`.
     - Remove tile from `t1_cycle1_tile` tracking so no post-season Cycle 3 is attempted.
3. **Days 24–25 Non-T1 Empty Tiles**:
   - Standard baseline behavior is preserved: empty core tiles that are not part of an ongoing T1 sequence continue to plant `WHEAT` (where 1 cycle matures on Day 28–29 for +$90 net profit).

---

## 4. Formal Power Analysis & Tournament Design

### 4.1 Measured Empirical Parameters
From the P5.0-R revalidation across 100 discovery games:
- Expected Paired Delta: $\mu_\Delta = \mathbf{+\$655.25 / \text{game}}$
- Paired Standard Deviation: $\sigma_\Delta = \mathbf{\$801.01}$
- Significance Level: $\alpha = 0.05$ (two-sided, $z_{\alpha/2} = 1.960$)
- Statistical Power Target: $1 - \beta = 0.80$ ($z_\beta = 0.8416$)

### 4.2 Minimum Sample Size Formula
$$N = \left( \frac{z_{\alpha/2} + z_\beta}{\mu_\Delta / \sigma_\Delta} \right)^2 = \left( \frac{1.960 + 0.8416}{655.25 / 801.01} \right)^2 = \left( \frac{2.8016}{0.8180} \right)^2 \approx \mathbf{11.7\text{ games}}$$

### 4.3 Evaluation on the Formal Reserved Tournament Block
- **Reserved Tournament Block**: Seeds `98,001–98,050` (50 seeds $\times 5\text{ opponents} \times 2\text{ seats} = \mathbf{500\text{ matches}}$).
- These seeds have been preserved 100% untouched throughout all diagnostic and repair phases.
- **Statistical Power with $N = 500$**:
  - Standard Error of the Mean: $SE = \frac{\$801.01}{\sqrt{500}} = \mathbf{\$35.82}$
  - Minimum Detectable Effect (MDE) at 80% power:
    $$\text{MDE} = 2.8016 \times \$35.82 = \mathbf{\$100.35}$$
  - Since the expected effect ($\$655.25$) is **6.5x larger than the MDE**, the statistical power of the 500-game tournament is:
    $$\text{Power} > \mathbf{99.99\%}$$

---

## 5. Formal Tournament Execution Protocol

1. **Step 1: Code Freeze & Unit Testing**:
   - Implement `config.py` flag and `macro_planner.py` logic.
   - Run complete unit test suite (`agent/tests/`) verifying bit-for-bit control identity when flag is OFF.
2. **Step 2: Pre-Tournament Discovery Replay**:
   - Run matched 100-game discovery panel (`96,201–96,210`).
   - Confirm live empirical delta is within the 95% confidence interval of predicted shadow delta (+$655.25 $\pm$ $157.00).
   - Confirm 0.0% herd starvation.
3. **Step 3: Formal 500-Game Tournament Execution**:
   - Run Control (Flag OFF) on `98,001–98,050` (500 games).
   - Run Treatment (Flag ON) on `98,001–98,050` (500 games).
   - Compute paired deltas, win-rate lift, and opponent-by-opponent breakdowns.
4. **Step 4: Release Decision Gates**:
   - Criterion A: Paired mean delta $\mu_\Delta > 0$ with $p < 0.01$.
   - Criterion B: Win rate improvement $\ge +1.0\%$.
   - Criterion C: Herd starvation rate strictly $0.0\%$.
   - Criterion D: Zero cash reconciliation discrepancies ($0.00).
