# P6.1-C Outlier Distribution Analysis

## Executive Summary

This report analyzes the distribution of paired cash deltas across all 100 scenario pairs to determine whether the reported +$1,439.86/game mean cash advantage is a robust, typical effect or an artifact of heavy right-tail outliers.

Key findings:
1. **Severe Right-Tail Concentration**: 
   - The top **1 single pair** accounts for **12.1%** of the entire aggregate cash gain across all 100 games.
   - The top **5 pairs** account for **53.2%** of the total gain.
   - The top **10 pairs** account for **89.6%** of the total gain.
2. **Median is Less Than Half the Mean**:
   - Arithmetic Mean: **+$1,439.86**
   - 10% Trimmed Mean: **+$1,194.20**
   - Median Cash Delta: **+$642.50**
3. **Win Rate**:
   - Treatment won **57 out of 100 pairs (57.0%)**.
   - Control won **43 out of 100 pairs (43.0%)**.
   - The win rate is only marginally above 50%, reflecting high variance rather than systematic dominance.

---

## 1. Summary Statistics of Cash Delta Distribution

| Metric | Value |
| :--- | :---: |
| **Total Scenario Pairs** | 100 |
| **Total Aggregate Cash Delta** | **+$143,986.00** |
| **Mean Cash Delta** | **+$1,439.86** |
| **Median Cash Delta** | **+$642.50** |
| **10% Trimmed Mean** | **+$1,194.20** |
| **Standard Deviation** | $5,821.45 |
| **Interquartile Range (IQR)** | [-$1,475.00, +$3,864.00] ($5,339.00) |
| **Minimum Cash Delta** | -$17,498.00 (`s96414_pass_seat1`) |
| **Maximum Cash Delta** | +$17,358.00 (`s96415_cow_milk_engine_seat0`) |
| **Treatment Win Rate** | **57.0%** (57 Wins, 43 Losses, 0 Ties) |

---

## 2. Outlier Concentration Table

The total cumulative gain across all 100 pairs is **+$143,986.00**.

| Grouping | Cumulative Cash Delta | Share of Total Net Gain | Interpretation |
| :--- | :---: | :---: | :--- |
| **Top 1 Pair** | **+$17,358.00** | **12.1%** | Single extreme outlier |
| **Top 5 Pairs** | **+$76,633.00** | **53.2%** | More than half of all net gains |
| **Top 10 Pairs** | **+$129,000.00** | **89.6%** | Nearly 90% of all net gains |
| **Remaining 90 Pairs** | **+$14,986.00** | **10.4%** | Average +$166.51/game across 90 games |
| **Bottom 5 Pairs** | **-$53,411.00** | **-37.1%** | Severe negative downside in 5 games |

---

## 3. Top 5 Outlier Pairs Detail

| Rank | Scenario Identifier | Cash Delta | Discard Delta | Sales Delta | Expenditure Delta | Causal Driver |
| :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **#1** | `s96415_cow_milk_engine_seat0` | **+$17,358.00** | +13.0 u | +$19,582.00 | +$2,224.00 | Massive milk/crop sales divergence |
| **#2** | `s96418_melon_sniper_seat0` | **+$15,897.00** | -27.0 u | +$21,017.00 | +$5,120.00 | Melon price peak captured |
| **#3** | `s96414_pure_wheat_rush_seat0` | **+$14,832.00** | +51.0 u | +$18,539.00 | +$3,707.00 | Opponent stock depletion synergy |
| **#4** | `s96417_pure_wheat_rush_seat0` | **+$14,273.00** | +13.0 u | +$11,105.00 | -$3,168.00 | Wheat buffer preserved feed store |
| **#5** | `s96417_pure_wheat_rush_seat1` | **+$14,273.00** | +13.0 u | +$11,105.00 | -$3,168.00 | Symmetrical seat replication |

Notice that in 4 of the top 5 games, Treatment actually suffered **MORE discards than Control** (positive discard delta indicates Treatment had higher discards), yet earned $14k–$17k more cash! This proves that the cash gain in these top games was completely uncoupled from storage discard reduction.

---

## 4. Bottom 5 Downside Outlier Pairs Detail

| Rank | Scenario Identifier | Cash Delta | Discard Delta | Sales Delta | Expenditure Delta | Causal Driver |
| :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **#1** | `s96414_pass_seat1` | **-$17,498.00** | -18.0 u | -$14,364.00 | +$3,134.00 | Desynchronized harvest sale timing |
| **#2** | `s96411_cow_milk_engine_seat0` | **-$10,817.00** | -24.0 u | -$3,613.00 | +$7,204.00 | Animal feed disruption & over-spend |
| **#3** | `s96413_pass_seat0` | **-$8,688.00** | -19.0 u | -$642.00 | +$8,046.00 | Unfavorable town buy timing |
| **#4** | `s96413_pass_seat1` | **-$8,688.00** | -19.0 u | -$642.00 | +$8,046.00 | Symmetrical seat replication |
| **#5** | `s96416_full_production_agent_seat0` | **-$7,720.00** | -32.0 u | -$4,164.00 | +$3,556.00 | Opponent market preemption in wool |

In all 5 bottom games, Treatment achieved **substantial discard reductions** (saving 18–32 units from shed overflow), yet **lost between $7,700 and $17,500 in final cash**!

---

## 5. Methodological Conclusion

The cash delta distribution is highly volatile, sensitive to path-dependent harvest timing, and heavily skewed:
- **89.6%** of the net gain comes from just 10 matches.
- In the typical match, the median cash improvement is **+$642.50**.
- The 43% loss rate and severe downside outliers demonstrate that the P6.1 intervention introduced substantial behavioral instability into downstream planner decisions.
