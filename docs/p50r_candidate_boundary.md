# P5.0-R Candidate Decision Boundary Specification

## 1. Executive Summary

Phase P5.0-R establishes that the Late-Wheat Crop Substitution (T1) opportunity cannot be implemented as a coarse blanket policy across Days 21–25. Doing so inadvertently converts Day 24–25 wheat into unprofitable single-cycle carrots, inflicting severe economic damage (-$24.50 per tile, -$300.91 per game).

Instead, the candidate decision boundary must be mathematically refined to isolate the exact parameter subspace where **two 3-day carrot cycles fit safely before the season cutoff**.

---

## 2. Formal Specification of the Refined Decision Boundary

A candidate planting action is approved for T1 substitution if and only if **all five** of the following predicate conditions evaluate to `TRUE`:

```
T1_Candidate_Approved(tile, day, hour, state) =
    (21 <= day <= 23)                                       [Temporal Gate]
    AND (Feed_Ledger_Min_Balance(state, remove_wheat=True) >= Safety_Buffer)  [Feed Security Gate]
    AND (day + 6 <= 29)                                     [Two-Cycle Maturation Gate]
    AND (hour <= 17 AND money >= 20.00)                     [Operational Executability Gate]
    AND (Expected_Net_Delta(tile, day, market) > 0)          [Economic Surplus Gate]
```

### Detailed Predicate Definitions:
1. **Temporal Gate (`21 <= day <= 23`)**:
   - Strictly confines the policy to the 3 calendar days where two full 3-day crop cycles (planting to harvest) can terminate on or before Day 29.
   - Day 21 matures Cycle 2 on Day 27.
   - Day 22 matures Cycle 2 on Day 28.
   - Day 23 matures Cycle 2 on Day 29.
   - Any planting on Day 24+ is barred from carrot substitution and remains with baseline wheat replanting.
2. **Feed Security Gate (`B_min >= beta`)**:
   - The Time-Indexed Dynamic Ledger projects feed stock through Day 28 assuming the candidate tile is NOT wheat.
   - Requires $B_{\min} \ge \beta \equiv 1.0 \times N_{\text{herd}}$ (at least 1 full animal-day of buffer on every future day through Day 28).
3. **Two-Cycle Maturation Gate (`day + 6 <= 29`)**:
   - Mathematically verifies that Cycle 2 harvest step $\le 719$.
4. **Operational Executability Gate (`hour <= 17, cash >= $20`)**:
   - Ensures that the newly planted carrot seed can be watered today before Hour 24 (preventing weed conversion overnight).
   - Verifies sufficient liquid cash to purchase the carrot seed ($20.00).
5. **Economic Surplus Gate (`Delta > 0`)**:
   - Evaluates current market inventory $I_{\text{mkt}}[\text{CARROT}]$.
   - Confirms that the projected revenue of 6 carrots minus $40 seed costs and task displacement penalty exceeds the projected revenue of 4 wheat minus $10 seed cost.

---

## 3. Boundary Search Grid Across Cutoffs & Buffers

We evaluated alternative boundary parameterizations across the 100 discovery games to evaluate robustness:

| Day Cutoff | Buffer Threshold ($\beta$) | Mean Delta / Game | Median Delta / Game | Std Dev | Min Delta | Max Delta | Positive Games % |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Days 21–23 (Refined T1)** | **$\ge 1.0 \times \text{Herd}$** | **+$655.25** | **+$500.00** | **$801.01** | **$0.00** | **+$5,538.00** | **67.0%** |
| Day $\ge 21$ (Coarse) | $\ge 0.0$ | +$212.47 | +$214.00 | $1,571.21 | -$2,223.00 | +$5,538.00 | 58.0% |
| Day $\ge 22$ (Coarse) | $\ge 0.0$ | +$9.30 | -$14.00 | $1,412.59 | -$2,294.00 | +$5,014.00 | 49.0% |
| Day $\ge 23$ (Coarse) | $\ge 0.0$ | -$128.97 | -$87.00 | $1,091.23 | -$1,909.00 | +$3,932.00 | 44.0% |
| Day $\ge 24$ (Coarse) | $\ge 0.0$ | -$300.91 | -$315.00 | $724.59 | -$1,470.00 | +$2,312.00 | 25.0% |
| Day $\ge 25$ (Coarse) | $\ge 0.0$ | -$133.84 | -$133.00 | $395.17 | -$990.00 | +$1,789.00 | 24.0% |

### Why Coarse Boundaries Fail:
Notice that coarse day boundaries that substitute ALL wheat on Day $\ge 24$ or Day $\ge 25$ experience substantial net losses (-$300.91/game). This occurs because unconstrained substitution forces single-cycle carrots that net only $85 (vs $90 for wheat), destroying capital.

Only the **Refined Boundary (Days 21–23 with 2 cycles)** achieves a positive, high-confidence gain with zero downside.

---

## 4. Production Policy Pseudocode for P5.1

```python
def should_apply_t1_carrot_substitution(ctx, tile_pos, current_plan):
    day = ctx["day"]
    hour = ctx["hour"]
    
    # 1. Temporal Gate: Days 21-23 only
    if not (21 <= day <= 23):
        return False
        
    # 2. Executability Gate: Must be plantable and waterable today
    if hour > 17 or ctx["farm"].money < 20.0:
        return False
        
    # 3. Two-Cycle Fit Gate
    if day + 6 > 29:
        return False
        
    # 4. Feed Security Gate (Time-Indexed Dynamic Ledger)
    is_safe, min_buf = simulate_feed_ledger(ctx, exclude_tile=tile_pos)
    required_buf = float(len([a for a in ctx["farm"].animals if a.species in ("COW", "SHEEP")]))
    if not is_safe or min_buf < required_buf:
        return False
        
    # 5. Economic Gate: Carrot must beat Wheat under current market prices
    c_rev = estimate_two_cycle_carrot_revenue(ctx)
    w_rev = estimate_one_cycle_wheat_revenue(ctx)
    net_c = c_rev - 40.0  # Two seeds
    net_w = w_rev - 10.0  # One seed
    if (net_c - net_w) <= 0:
        return False
        
    return True
```
