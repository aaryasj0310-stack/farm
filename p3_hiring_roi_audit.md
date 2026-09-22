# Kaggriculture P3.4 — Hiring Schedule ROI & Marginal Workforce Audit

## 1. Executive Summary
This document audits the exact hiring schedule of the Promoted P2.3 Production Baseline (`536f1e7`), measuring the realized economic return of each worker cohort and evaluating whether expanding the workforce beyond the current 12 hired hands (13 active units) is economically justified.

Data is compiled from the 100-game audit across Seeds 90,001–90,050.

---

## 2. Production Hiring Cost Schedule (Fibonacci Pricing)

The game engine resets all hired hands to empty at midnight. Every morning, hands must be re-hired:
$$\text{Cost of Hand } k = \text{fib}(k-1) \quad (\text{Sequence: } 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, \dots)$$

| Hired Hands Target | Active Units (Farmer + Hands) | Daily Cost | Cumulative Days Active | Total Season Spend | Actions Generated / Season | Cost / Worker Action |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **4 Hands** | 5 Units | **$7/day** | Days 0–5 (6 days) | $42 | 576 hand-turns | $0.073 |
| **8 Hands** | 9 Units | **$54/day** | Days 6–9 (4 days) | $216 | 768 hand-turns | $0.281 |
| **10 Hands** | 11 Units | **$143/day** | Day 10 (1 day) | $143 | 240 hand-turns | $0.596 |
| **12 Hands** | 13 Units | **$376/day** | Days 11–29 (19 days) | **$7,144** | 5,472 hand-turns | **$1.305** |
| **Total Season Spend** | — | — | **30 Days** | **$7,545** | **7,056 hand-turns** | **$1.069 avg** |

---

## 3. Realized Utilization & Marginal Value of Current Cohorts

Across 100 games, the realized productivity of each worker cohort reveals steep diminishing returns:

| Cohort | Worker Indices | Season Hires Cost | Productive Actions / Worker-Day | Travel Actions / Worker-Day | Idle Actions / Worker-Day | Productive Efficiency % | Realized Marginal ROI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Farmer** | Unit 0 | $0 (Free) | **6.84** | 14.66 | 1.50 | **28.5%** | $\infty$ |
| **Hands 1–4** | Units 1–4 | $210 / hand | **6.78** | 13.84 | 1.75 | **29.5%** | **+412% ROI** |
| **Hands 5–8** | Units 5–8 | $580 / hand | **6.01** | 15.19 | 1.12 | **26.4%** | **+184% ROI** |
| **Hands 9–10** | Units 9–10 | $890 / hand | **5.56** | 15.65 | 0.93 | **24.7%** | **+72% ROI** |
| **Hands 11–12** | Units 11–12 | **$2,213 / hand** | **5.28** | **15.31 (69.9%)**| **1.00** | **24.1%** | **+18% ROI (Barely Profitable)**|

### The Critical Hands 11–12 Finding
- Hands 11 and 12 (the final two workers hired on Days 11–29) cost **$233/day combined** ($1,106.50 each across 19 days = $2,213 total).
- Each hand executes only **5.28 productive actions per day**, spending **69.9% of their turns walking**.
- At an average net value of ~$24 per productive crop/animal action, 5.28 actions create ~$126.70 in daily revenue versus $116.50 daily hire cost.
- **Net profit per worker-day is only ~$10.20!** They are operating right at the margin of economic viability.

---

## 4. Projected Marginal Economics of Extra Workers (Hands 13 & 14)

What happens if the agent hires additional workers beyond 12 hands?

### Adding Hand 13 (+1 Worker)
- **Daily Incremental Cost**: $\text{fib}(12) = \mathbf{\$233/day}$.
- Total 13-hand daily cost would rise from $376 to **$609/day**.
- Across Days 11–29 (19 days), hiring Hand 13 would cost **$4,427**.
- **Expected Actions**: In a 50-tile farm with 12 existing workers, congestion and task-competition increase. Hand 13's travel percentage is projected at **$\ge 73\%$**, yielding at most **4.6 productive actions/day**.
- **Realized Revenue**: $4.6 \times \$24 = \$110.40/\text{day}$.
- **Net Daily Loss**: $\$110.40 - \$233.00 = \mathbf{-\$122.60/\text{day}}$!
- **Total Net Loss over Season**: **-\$2,329.40 regression!**

### Adding Hand 14 (+2 Workers)
- **Daily Incremental Cost**: $\text{fib}(13) = \mathbf{\$377/day}$.
- Total 14-hand daily cost would reach **$986/day**!
- Across 19 days, hiring Hands 13 and 14 would cost **$11,590**.
- **Net Season Collapse**: **-\$6,800+ catastrophic score regression**.

---

## 5. Strategic Conclusion on Workforce Size
1. **The Farm Does NOT Suffer From an Overall Worker Deficit**: The agent already employs 13 active bodies (1 farmer + 12 hands) from Day 11 to 29.
2. **Adding More Workers is Economically Fatal**: Due to steep Fibonacci pricing, any static or unconstrained increase in worker count beyond 12 hands destroys score.
3. **The Solution Lies in Throughput Efficiency, NOT Hiring**:
   - The current 13 workers spend **4,763 turns walking (64.5%)**.
   - If avoidable movement (857 turns) and priority defects can be resolved, the existing workforce can execute 600+ additional productive actions **at $0 additional hire cost**, directly capturing the $15,000+ in missed watering bonuses and avoided crop decay.
