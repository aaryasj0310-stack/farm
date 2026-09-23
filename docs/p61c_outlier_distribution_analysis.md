# P6.1-C Outlier Distribution Analysis (Corrected)

## Executive Summary

This report analyzes the distribution of paired cash deltas across all 100 scenario pairs to determine whether the reported +$1,439.86/game mean cash advantage is a robust, typical effect or an artifact of heavy right-tail outliers.

Key findings:
1. **Severe Right-Tail Concentration**: 
   - The top **1 single pair** accounts for **12.1%** of the entire aggregate cash gain across all 100 games.
   - The top **5 pairs** account for **53.2%** of the total gain.
   - The top **10 pairs** account for **89.6%** of the total gain.
   - Excluding the top 10 pairs, the remaining 90 pairs average only **+$166.51/game**.
2. **Median is Less Than Half the Mean**:
   - Arithmetic Mean: **+$1,439.86**
   - 10% Trimmed Mean: **+$1,250.08** *(Corrected from earlier +$1,194.20 draft; verified via `scipy.stats.trim_mean` on slice `[10:90]`)*
   - Even-$N$ Median Cash Delta: **+$642.50**
3. **Win Rate**:
   - Treatment won **58 out of 100 pairs (58.0%)**.
   - Control won **42 out of 100 pairs (42.0%)**.
   - Ties: **0**.

---

## 1. Summary Statistics of Cash Delta Distribution

| Metric | Corrected Value | Notes |
| :--- | :---: | :--- |
| **Total Scenario Pairs** | 100 | Discovery seeds `96,411`–`96,420` |
| **Total Aggregate Cash Delta** | **+$143,986.00** | Net across all 100 pairs |
| **Mean Cash Delta** | **+$1,439.86** | Per-pair arithmetic mean |
| **Even-$N$ Median Cash Delta** | **+$642.50** | Average of 50th and 51st sorted pairs |
| **10% Trimmed Mean** | **+$1,250.08** | Slicing sorted deltas `[10:90]` (80 observations) |
| **Sample Standard Deviation ($s$)** | **$5,826.27** | High game-to-game variance |
| **Standard Error ($SE$)** | **$582.63** | $s / \sqrt{100}$ |
| **95% Confidence Interval** | **[+$297.91, +$2,581.81]** | Statistically positive at 95% confidence |
| **Minimum Cash Delta** | -$17,498.00 | `s96414_pass_seat1` |
| **Maximum Cash Delta** | +$17,358.00 | `s96415_cow_milk_engine_seat0` |
| **Treatment Win Rate** | **58.0%** | 58 Wins, 42 Losses, 0 Ties |

---

## 2. Outlier Concentration Table

The total cumulative gain across all 100 pairs is **+$143,986.00**.

| Grouping | Cumulative Cash Delta | Share of Total Net Gain | Mean Excluding Group |
| :--- | :---: | :---: | :---: |
| **Top 1 Pair** | **+$17,358.00** | **12.1%** | +$1,279.07 |
| **Top 5 Pairs** | **+$76,633.00** | **53.2%** | +$708.98 |
| **Top 10 Pairs** | **+$129,000.00** | **89.6%** | +$166.51 |
| **Remaining 90 Pairs** | **+$14,986.00** | **10.4%** | +$166.51 |
| **Bottom 5 Pairs** | **-$53,411.00** | **-37.1%** | — |

---

## 3. Resolution of the Trimmed Mean Discrepancy

In an earlier P6.1-C draft, the 10% trimmed mean was reported as **+$1,194.20**.
Re-evaluation directly from the committed paired results establishes that:
- Slicing the sorted 100 deltas to drop the lowest 10 and highest 10 observations (`s_deltas[10:90]`) yields exactly **+$1,250.08**.
- This is identically confirmed by `scipy.stats.trim_mean(deltas, 0.10) == 1250.075`.
- The previous +$1,194.20 figure resulted from a boolean mask indexing error. The exact, defensible 10% trimmed mean is **+$1,250.08**.

---

## 4. Methodological Conclusion

The cash delta distribution is heavily skewed:
- **89.6%** of the net gain comes from just 10 matches.
- However, even after trimming the top and bottom 10% of games, the 10% trimmed mean remains firmly positive at **+$1,250.08**.
- The 95% confidence interval `[+$297.91, +$2,581.81]` confirms that the positive cash signal is not entirely random noise, but reflects the real underlying benefits of on-farm feed retention and occasional discard salvage.
