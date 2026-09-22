# P5.0 Strawberry Lifecycle & Retention Boundary Audit

## Lifecycle Profile

Strawberry is an ongoing multi-flush crop:
- **First Yield**: Day $D+9$ (if watered daily).
- **Yield Interval**: Every 3 days thereafter ($D+12, D+15, D+18$).
- **Maximum Flushes**: 4 harvest flushes.
- **Base Yield**: 1 unit per flush (2 units if watered and fertilized).
- **Market Dynamics**: High base value ($120), steep decay curve with town market supply.

---

## Empirical Core Allocation

Across 100 games:
- **Total Tile-Days Occupied**: 22,916 tile-days (15.3% of core).
- **Primary Locality**: Northeast Quadrant (18,377 tile-days) unlocked between Days 7 and 11.
- **Fertilizer Applications**: 1,964 applications on Strawberries (1512 F1, 452 F2).
- **Mean Net Fertilizer Marginal Value**: **+$65.28** per application!

---

## Late-Season Retention vs Replacement Boundary

A key strategic question is whether late-season Strawberry plants should be kept for residual harvests or dug up and replaced with Carrots:
- On **Day 21**:
  - A strawberry plant that has completed 3 flushes has only 1 flush remaining (Day 24). Expected marginal revenue = 1–2 units @ ~$100 = $100–$200 gross, requiring 3 more days of watering.
  - If dug on Day 21, the tile can support **two full Carrot cycles** (Day 21->24, Day 24->27), yielding 4 units of carrots @ ~$40 = $160 gross with substantially lower watering risk.
- On **Day 24+**:
  - If all 4 flushes are exhausted, the strawberry vine is barren (`harvest_count == 4`). The baseline agent leaves these barren vines in the ground for an average of 4.2 tile-days before digging!
- **T3 Opportunity**: Automatically dig exhausted strawberry vines immediately after flush 4 and replant with quick-turn Carrots.
