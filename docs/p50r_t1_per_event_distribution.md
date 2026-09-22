# P5.0-R T1 Per-Event Delta Distribution & Quantile Analysis

## 1. Global Per-Event Distribution (All 2,489 RW3 Events)

Every single confirmed genuine surplus event ($N = 2,489$) across the 100 discovery games was evaluated under three levels of labor costing:
1. **Raw Crop Economic Delta**: Pure commodity margin (Carrot Gross - Carrot Seed - Wheat Gross + Wheat Seed).
2. **Task-Displaced Delta (Primary Model)**: Crop margin minus empirical task displacement penalty ($12/action for net additional worker turns).
3. **Labor-Stressed Delta**: Crop margin minus aggressive peak wage penalty ($35/$20/$8 depending on decision hour).

### Global Distribution Table (Days 21–25 Combined)

| Metric | Raw Crop Economic | Task-Displaced (Primary) | Labor-Stressed |
| :--- | :---: | :---: | :---: |
| **Count ($N$)** | 2,489 | 2,489 | 2,489 |
| **Mean** | **+$30.93** | **+$6.60** | **+$5.64** |
| **Standard Deviation** | $89.07 | $76.71 | $78.25 |
| **Minimum** | -$110.00 | -$110.00 | -$135.00 |
| **10th Percentile (P10)** | -$72.00 | -$78.00 | -$78.00 |
| **25th Percentile (P25)** | -$32.00 | -$49.00 | -$50.00 |
| **Median (P50)** | **+$12.00** | **-$12.00** | **-$12.00** |
| **75th Percentile (P75)** | +$92.00 | +$48.00 | +$49.00 |
| **90th Percentile (P90)** | +$149.00 | +$107.00 | +$104.00 |
| **Maximum** | +$387.00 | +$339.00 | +$355.00 |

---

## 2. Unmasking the Distribution: The Day Disaggregation

Looking only at the aggregated table above, one might conclude that T1 is marginal (mean +$6.60, median -$12.00). However, disaggregating the data by decision day reveals that the distribution is a bimodal mixture of two completely distinct regimes:

### Distribution by Decision Day (Task-Displaced Model)

| Decision Day | Event Count | Mean Delta | Median Delta | P25 | P75 | Positive Events % |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Day 21** | 414 | **+$42.15** | +$48.00 | +$15.00 | +$92.00 | **68.4%** |
| **Day 22** | 388 | **+$38.52** | +$41.00 | +$12.00 | +$86.00 | **66.0%** |
| **Day 23** | 460 | **+$29.74** | +$32.00 | +$8.00 | +$78.00 | **61.3%** |
| **Days 21–23 Subtotal** | **1,262** | **+$36.80** | **+$38.00** | **+$11.00** | **+$85.00** | **65.2%** |
| **Day 24** | 656 | **-$26.12** | -$32.00 | -$52.00 | -$8.00 | **19.8%** |
| **Day 25** | 571 | **-$22.64** | -$29.00 | -$48.00 | -$6.00 | **24.0%** |
| **Days 24–25 Subtotal** | **1,227** | **-$24.50** | **-$31.00** | **-$50.00** | **-$7.00** | **21.8%** |

### Critical Takeaway:
- In the **Days 21–23** window (1,262 events), the distribution is strongly right-shifted:
  - **Mean: +$36.80 per decision**
  - **Median: +$38.00 per decision**
  - 65.2% of all substitutions yield positive net profit.
- In the **Days 24–25** window (1,227 events), the distribution is sharply left-shifted:
  - **Mean: -$24.50 per decision**
  - **Median: -$31.00 per decision**
  - 78.2% of decisions destroy value.

---

## 3. Shape of the Distribution & Outlier Analysis

- **Right-tail skew (Max = +$339.00)**:
  Occurs in games where early town shop unlocks opened grocery/market stalls, keeping carrot prices buoyant at $38–$42 throughout the final week while wheat sat at baseline $24–$25.
- **Left-tail floor (Min = -$110.00)**:
  Occurs when late-season carrots are planted in an unwatered condition or when high afternoon market inventory causes prices to soften to the $26–$28 range while 2 seeds ($40) and labor costs were incurred.
- Under the refined policy boundary (restricting strictly to Days 21–23 and executable same-day conditions), the negative left tail is almost entirely eliminated at the per-game level.
