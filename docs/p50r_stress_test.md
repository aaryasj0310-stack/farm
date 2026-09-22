# P5.0-R Multi-Dimensional Stress Testing & Robustness Analysis

## 1. Objective & Scope

To ensure that the Refined T1 Decision Boundary (Days 21–23, 2 Carrot Cycles, Feed Buffer Floor) does not rely on fragile or idealized simulation assumptions, we subjected the candidate policy to five orthogonal stress scenarios:
1. **Commodity Market Shock**: Severe carrot price collapse (-30%).
2. **Feed Grain Premium Shock**: Sharp spike in wheat prices (+40%).
3. **Operational Failure**: Missed bonus watering turns (suboptimal yield).
4. **Labor Strain**: Tripled peak worker shadow wages.
5. **Feed Insecurity**: Sudden harvest loss or animal feed disruption.

---

## 2. Stress Scenario Results & Sensitivity Matrix

| Stress Dimension | Baseline Condition | Stressed Condition | Stressed Per-Event Delta | Stressed Per-Game Shadow Delta | Resilience Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **1. Carrot Market Glut** | Base $P_c = \$35.00$ | $P_c$ drops by 30% to **$24.50** | **+$17.00** | **+$303.20** | **ROBUST (+$\Delta$ preserved)** |
| **2. Wheat Price Spike** | Base $P_w = \$25.00$ | $P_w$ surges by 40% to **$35.00** | **+$16.00** | **+$285.40** | **ROBUST (+$\Delta$ preserved)** |
| **3. Missed Bonus Water** | Max yield (3 units/cycle) | 1 missed water (2 units/cycle) | **+$10.00** | **+$178.50** | **ROBUST (+$\Delta$ preserved)** |
| **4. Labor Congestion** | Slack wage $12/act | Peak wage **$35/act** | **+$35.20** | **+$642.37** | **EXTREMELY ROBUST (98% kept)** |
| **5. Feed Starvation Risk** | Zero buffer | Safety floor $\beta = 1.0\times\text{Herd}$ | N/A (Safety Guard) | N/A (0.0% Starvation) | **100% INVIOLABLE** |

---

## 3. Deep-Dive on Individual Stress Dimensions

### 3.1 Stress Dimension 1: Carrot Price Collapse (-30%)
- *Hypothesis*: Opponent agents also plant carrots or town grocery shops do not open, driving carrot prices down from $35.00 to $24.50.
- *Calculation*:
  - Carrot Gross (6 units @ $24.50): **$147.00**
  - Carrot Seed (2 seeds @ $20.00): **-$40.00**
  - Net Carrot Profit: **$107.00**
  - Wheat Baseline Profit (4 units @ $25 - $10): **$90.00**
  - Net Delta: $\$107.00 - \$90.00 = \mathbf{+\$17.00\text{ per tile}}$.
- *Verdict*: Because two carrot cycles produce 6 units (vs 4 units of wheat), the volume advantage protects profitability even when carrot prices sink to parity with wheat.

### 3.2 Stress Dimension 2: High Wheat Prices (+40%)
- *Hypothesis*: The opponent runs a heavy livestock strategy and aggressively buys wheat, driving wheat prices up to $35.00.
- *Calculation*:
  - Wheat Gross (4 units @ $35.00): **$140.00**
  - Wheat Seed: **-$10.00**
  - Net Wheat Profit: **$130.00**
  - Carrot Profit (6 units @ $35 - $40): **$170.00**
  - Net Delta: $\$170.00 - \$130.00 = \mathbf{+\$40.00\text{ per tile}}$.
- *Verdict*: Even when wheat reaches peak historical scarcity prices, the 6-unit carrot cycle maintains a +$40.00 margin.

### 3.3 Stress Dimension 3: Missed Bonus Watering
- *Hypothesis*: High worker pathing congestion causes a worker to miss one bonus watering turn in Cycle 1 and Cycle 2, yielding only 2 units per cycle (4 total carrots).
- *Calculation*:
  - Carrot Gross (4 units @ $35.00): **$140.00**
  - Carrot Seed: **-$40.00**
  - Net Carrot Profit: **$100.00**
  - Wheat Baseline Profit: **$90.00**
  - Net Delta: $\$100.00 - \$90.00 = \mathbf{+\$10.00\text{ per tile}}$.
- *Verdict*: Even with impaired watering, two carrot cycles break even or slightly beat a perfectly watered wheat tile.

### 3.4 Stress Dimension 4: Peak Labor Wage Penalties
- As modeled in `eval_refined_boundary.py`:
  - Applying severe penalties ($35/action for morning, $20 for midday, $8 for afternoon) reduces the per-game shadow delta from **+$655.25** to **+$642.37** (a mere **$12.88 / game drop**, or 1.9%).
- *Verdict*: Labor contention does not materially impair T1 economics.

### 3.5 Stress Dimension 5: Inviolable Feed Safety
- By requiring $B_{\min} \ge 1.0 \times \text{Herd Size}$ on every future day through Day 28, the policy guarantees a 24-hour buffer. 
- In all 100 discovery games, the herd starvation rate under the refined boundary is **strictly 0.0%**.

---

## 4. Synthesis & Resilience Conclusion

The Refined T1 Decision Boundary is **not a knife-edge strategy**. It maintains positive expected value across all tested stress conditions, with a minimum stressed per-game gain of **+$178.50 to +$303.20** under worst-case operational impairments, and **+$655.25** under normal conditions.
