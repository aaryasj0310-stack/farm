# Kaggriculture P5.1-C — Inventory Overflow & Endgame Liquidation Audit

## 1. Executive Summary

This report evaluates inventory dynamics, shed capacity constraints, discarded overflow losses, and final endgame liquidation across all 100 matched pairs (200 live games).

### Key Audit Findings:
1. **Flawless Endgame Liquidation (0.00 Remaining Inventory)**:
   - In all 200 games, **zero unsold inventory** remained in either the shed or worker backpacks at the end of Day 29 (`final_shed = 0.00`, `final_worker_inv = 0.00`).
   - The endgame liquidator successfully converted 100% of available physical goods into cash on the final day. The −$1,020.68 deficit was NOT caused by unsold final stock.
2. **Shed Capacity Overflow Triggered Carrot Discards (+3.95 units)**:
   - Shed capacity in Kaggriculture is 100 units. At the end of each day (`_drop_inventories_to_shed`), worker inventories exceeding remaining shed capacity are permanently discarded by the engine.
   - Treatment discarded **+3.95 additional carrots per game** (1.14 $\rightarrow$ 5.09) due to intraday shed crowding when C1/C2 harvests coincided with livestock products.
   - Total discards rose from **41.63 units / game** in Control to **46.00 units / game** in Treatment (+4.37 units).
3. **Wool and Fertilizer Shed Collisions**:
   - Treatment also experienced a slight increase in discarded wool (+0.93 units) and fertilizer (+0.49 units).
   - Because carrots occupied 10–15 additional shed slots during Days 24–28, high-value wool and fertilizer had less headroom, resulting in occasional shed discards before market sell orders could clear space.

---

## 2. Discarded Overflow Accounting Table

The table below details physical units discarded panel-wide due to shed capacity overflows at daily resets:

| Commodity | Control Discarded (Units) | Treatment Discarded (Units) | Delta ($\Delta$ Units) | Estimated Cash Impact |
| :--- | :---: | :---: | :---: | :---: |
| **CARROT** | 1.14 | 5.09 | **+3.95** | −$166.25 (@ $42.09) |
| **WOOL** | 4.56 | 5.49 | **+0.93** | −$199.78 (@ $214.82)|
| **FERTILIZER** | 4.32 | 4.81 | **+0.49** | −$39.74 (@ $81.10) |
| **MELON** | 1.24 | 1.37 | **+0.13** | −$30.98 (@ $238.31)|
| **COW** (Animal) | 0.02 | 0.02 | **0.00** | $0.00 |
| **SHEEP** (Animal) | 0.01 | 0.01 | **0.00** | $0.00 |
| **TOMATO** | 0.57 | 0.54 | **−0.03** | +$2.05 |
| **MILK** | 4.19 | 4.06 | **−0.13** | +$31.73 |
| **STRAWBERRY** | 8.03 | 7.87 | **−0.16** | +$39.94 |
| **WHEAT** | 17.55 | 16.74 | **−0.81** | +$29.90 |
| **Total Discarded Units** | **41.63** | **46.00** | **+4.37** | **−$333.13** |

---

## 3. Endgame Liquidation Performance (Day 29)

The table below shows the liquidation audit for Day 29:

| Metric | Control Mean | Treatment Mean | Delta ($\Delta$) | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Day 29 Units Harvested** | 108.45 | 112.18 | **+3.73** | Fully collected |
| **Day 29 Units Sold** | 108.45 | 112.18 | **+3.73** | Fully liquidated |
| **End of Season Shed Stock** | **0.00** | **0.00** | **0.00** | 100% Cleared |
| **End of Season Worker Stock** | **0.00** | **0.00** | **0.00** | 100% Cleared |
| **Unsold Inventory Haircut** | **$0.00** | **$0.00** | **$0.00** | Zero haircut |

### Conclusion:
The liquidation logic performed flawlessly. However, shed capacity dynamics during Days 24–28 were tighter than realized: adding high-volume carrots into the 100-capacity shed crowded out storage, resulting in **+3.95 discarded carrots** and **+0.93 discarded wool units**, costing over **$300** in unrecoverable physical loss.
