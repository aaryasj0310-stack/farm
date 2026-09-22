# P5.0-R Wheat vs Carrot Counterfactual: Asymmetry of Days 21–23 vs Days 24–25

## 1. The Core Counterfactual Architecture

For each confirmed genuine surplus event ($i \in \text{RW3}$), we evaluate two mutually exclusive options for the candidate tile:

- **Counterfactual A (Status Quo Baseline — Keep Wheat)**:
  - Seed cost: $c_{\text{seed}, w} = \$10.00$.
  - Maturation: 4 days (Harvested on Day $P_i + 4$).
  - Expected unfertilized yield: $Y_w = 4$ units.
  - Gross market revenue: $R_w = \text{MarginalRevenue}(\text{WHEAT}, I_{\text{mkt}}, 4)$.
  - Net wheat profit: $\Pi_w = R_w - 10.00$.
  - Required worker actions: 6 actions (1 plant, 4 daily waterings, 1 harvest).

- **Counterfactual B (Treatment Alternative — Substitute Fast Carrot Rotations)**:
  - Seed cost per cycle: $c_{\text{seed}, c} = \$20.00$.
  - Maturation per cycle: 3 days (Harvested on Day $P + 3$).
  - Expected unfertilized yield per cycle: $Y_c = 3$ units.
  - Cycles feasible before season end ($D_{\text{end}} = 29$):
    $$N_{\text{cycles}} = \begin{cases} 2 & \text{if } P_i + 6 \le 29 \iff P_i \le 23 \\ 1 & \text{if } P_i + 3 \le 29 \text{ and } P_i + 6 > 29 \iff P_i \in \{24, 25, 26\} \end{cases}$$
  - Gross market revenue: $R_c = \sum_{k=1}^{N_{\text{cycles}}} \text{MarginalRevenue}(\text{CARROT}, I_{\text{mkt}}^{(k)}, 3)$.
  - Net carrot profit: $\Pi_c = R_c - (N_{\text{cycles}} \times 20.00)$.
  - Required worker actions: $5 \times N_{\text{cycles}}$ actions (1 plant, 3 waterings, 1 harvest per cycle).

---

## 2. The Critical Mathematical Asymmetry

The preliminary P5.0 analysis assumed a constant $+45.00$ gain for any late wheat converted to carrots. Rigorous modeling reveals that **the economic value is radically asymmetric across the Day 21–25 window**:

```
Day:       21      22      23      24      25      26      27      28      29      30 (End)
Wheat:     [--- 4-day Wheat Cycle ---] H                                            (Matures D25)
Carrot C1: [--- 3-day C1 ---] H
Carrot C2:                    [--- 3-day C2 ---] H                                  (Matures D27 <= 29!)

On Day 24:
Wheat:                             [--- 4-day Wheat Cycle ---] H                    (Matures D28 <= 29!)
Carrot C1:                         [--- 3-day C1 ---] H                             (Matures D27 <= 29!)
Carrot C2 (Fails):                                    [--- 3-day C2 ---] X          (Matures D30 > 29!)
```

### 2.1 Days 21–23: Two 3-Day Carrot Cycles Fit
- **Day 21 Planting**:
  - Cycle 1: Planted Day 21 $\rightarrow$ Harvested Day 24.
  - Cycle 2: Planted Day 24 $\rightarrow$ Harvested Day 27 ($\le 29$).
- **Day 22 Planting**:
  - Cycle 1: Planted Day 22 $\rightarrow$ Harvested Day 25.
  - Cycle 2: Planted Day 25 $\rightarrow$ Harvested Day 28 ($\le 29$).
- **Day 23 Planting**:
  - Cycle 1: Planted Day 23 $\rightarrow$ Harvested Day 26.
  - Cycle 2: Planted Day 26 $\rightarrow$ Harvested Day 29 ($\le 29$).

#### Economic Comparison (Two Cycles):
- **Wheat**: 4 units $\times \approx \$25 - \$10 = \mathbf{+\$90.00\text{ net}}$.
- **Carrot**: 6 units $\times \approx \$35 - \$40 = \mathbf{+\$170.00\text{ net}}$.
- **Raw Theoretical Surplus**: $\$170 - \$90 = \mathbf{+\$80.00\text{ per tile}}$.
- **Empirical Measured Mean**: **+$36.80 per event** (accounting for market inventory price depression and slot congestion).

### 2.2 Days 24–25: Only ONE Carrot Cycle Fits
- **Day 24 Planting**:
  - Cycle 1: Planted Day 24 $\rightarrow$ Harvested Day 27.
  - Cycle 2: Planted Day 27 $\rightarrow$ Matures Day 30 ($> 29$, post-season dead loss).
- **Day 25 Planting**:
  - Cycle 1: Planted Day 25 $\rightarrow$ Harvested Day 28.
  - Cycle 2: Cannot be planted.

#### Economic Comparison (Single Cycle):
- **Wheat**: 4 units $\times \approx \$25 - \$10 = \mathbf{+\$90.00\text{ net}}$.
- **Carrot**: 3 units $\times \approx \$35 - \$20 = \mathbf{+\$85.00\text{ net}}$.
- **Raw Theoretical Delta**: $\$85 - \$90 = \mathbf{-\$5.00\text{ per tile}}$.
- When factoring in carrot market inventory saturation and labor displacement:
  - **Empirical Measured Mean**: **-$24.50 per event**!
  - Over **78% of Day 24–25 substitutions are negative**.

---

## 3. Empirical Distribution: Days 21–23 vs Days 24–25

| Metric | Days 21–23 (2 Cycles Fit) | Days 24–25 (1 Cycle Only) | Full Window (Days 21–25) |
| :--- | :---: | :---: | :---: |
| **Total Events** | 1,262 | 1,227 | 2,489 |
| **Mean Raw Delta** | **+$84.73** | **-$24.47** | +$30.93 |
| **Mean Task-Displaced Delta** | **+$36.80** | **-$24.50** | +$6.60 |
| **Median Delta** | **+$38.00** | **-$31.00** | -$12.00 |
| **Positive Events %** | **65.2%** | **21.8%** | 43.8% |
| **Verdict** | **Highly Profitable (+$\Delta$)** | **Directly Destructive (-$\Delta$)** | **Diluted** |

---

## 4. Key Strategic Insight for Policy Design

This finding completely invalidates the coarse P5.0 hypothesis that "Days 21–25 wheat should be replaced with carrots".

1. **Days 24–25 Wheat is Optimal**:
   Wheat planted on Days 24–25 matures on Days 28–29, yielding 4 units for $10 seed. A single carrot cycle yields only 3 units for $20 seed. Wheat is mathematically and empirically superior to carrot when only 1 rotation fits.
2. **The T1 Opportunity Exists Exclusively on Days 21–23**:
   The entire economic advantage of T1 stems from executing **two back-to-back 3-day carrot cycles** within the remaining season window.
3. **Refined Decision Boundary Mandate**:
   Any viable P5.1 policy must hard-gate the substitution to **Days 21–23 only**. Expanding the rule to Days 24–25 destroys capital and degrades performance.
