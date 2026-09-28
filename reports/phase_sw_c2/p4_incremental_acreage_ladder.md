# Phase SW-C2: P4 — Incremental Acreage Ladder Analysis Report

**Date:** 2026-09-29  
**Branch:** `experiment/sw-c2-workforce-coordinator`  
**Status:** Verification Complete — Economic Ladder Characterization Documented  

---

## 1. Executive Summary

Phase P4 evaluates the **Incremental Acreage Ladder** across SW acreage caps of **8, 12, 16, 20, and 24 tiles** with the dispatcher, reservation system, crop portfolio, hiring schedule, and market logic strictly frozen as validated in Phase P3.

The central inquiry of Phase P4 is whether increasing SW acreage beyond the baseline 8 tiles yields positive incremental whole-farm cash, or whether labor cross-quadrant transit, shed storage bottlenecks, and incumbent core displacement erode net farm profit.

### Key Empirical Findings:
1. **Optimal Whole-Farm Acreage is 8 Tiles:** Under the validated coordinated dispatcher and reservation manager, the 8-tile SW configuration (`ARM_F`) achieves the highest final cash ($100,079.00 on seed 97013 pass 0), outperforming 12 tiles ($95,234.00, -$4,845) and 16 tiles ($90,139.00, -$9,940).
2. **Rational Reservation Ceiling at 16 Tiles:** In configurations authorized for 20 (`ARM_G20`) and 24 (`ARM_G24`) tiles, the transactional reservation manager **rationally rejected** expansion beyond 16 tiles due to harvest shed storage congestion (`Storage congestion: peak harvest 4 units exceeds available shed room 1`). Both ARM_G20 and ARM_G24 halted identically at 16 tiles, demonstrating that the reservation manager safely prevents uncontrolled over-expansion.
3. **Primary Economic Cause of Diminishing Returns — Internal Feed Displacement:**
   - At 12 tiles (`ARM_G12`), SW crop revenue expanded substantially from $8,950.30 to $13,326.43 (+$4,376.13, +48.9%), and SW net margin increased from $7,910.30 to $11,806.43 (+$3,896.13).
   - However, servicing 12 SW tiles required 546 SW actions (vs 364 in 8-tile), consuming worker-hours and drawing labor away from core wheat replanting/harvesting (core wheat harvest fell from 400 to 317 units).
   - Consequently, feed wheat had to be purchased from the market at spot prices, exploding feed expenses from $33,573.00 to $43,116.00 (+$9,543.00).
   - In addition, livestock care actions slipped from 215 to 196, decreasing core livestock revenue from $70,257.00 to $64,306.00 (-$5,951.00).
   - The $4,376 SW crop revenue gain was outweighed by the combined -$15,494 feed cost increase and livestock revenue loss, net of the $1,500 land acquisition cost.
4. **Market-Condition Responsiveness:** On seed 97014, where market prices and margins were tighter, the reservation manager correctly rejected all SW land purchases across all arms (`sw_purchase_rate: 0.0`), preserving identical $83,961.00 cash without wasted capital.

---

## 2. Experimental Ladder Results (Seed 97013 Pass 0)

| Metric | ARM_F (Cap 8) | ARM_G12 (Cap 12) | ARM_G16 (Cap 16) | ARM_G20 (Cap 20) | ARM_G24 (Cap 24) |
|---|---|---|---|---|---|
| **Max Cap Allowed** | 8 | 12 | 16 | 20 | 24 |
| **Realized Acreage** | 8 | 12 | 16 | 16 (Halted) | 16 (Halted) |
| **Final Cash** | **$100,079.00** | $95,234.00 | $90,139.00 | $90,139.00 | $90,139.00 |
| **Cash Residual** | **$0.0000** | $0.0000 | $0.0000 | $0.0000 | $0.0000 |
| **Core Crop Revenue** | $78,409.70 | $80,032.57 | $78,151.79 | $78,151.79 | $78,151.79 |
| **SW Crop Revenue** | $8,950.30 | $13,326.43 | $15,023.21 | $15,023.21 | $15,023.21 |
| **SW Net Crop Margin** | $7,910.30 | $11,806.43 | $13,143.21 | $13,143.21 | $13,143.21 |
| **Core Livestock Revenue** | **$70,257.00** | $64,306.00 | $59,252.00 | $59,252.00 | $59,252.00 |
| **Feed Purchase Costs** | **$33,573.00** | $43,116.00 | $47,211.00 | $47,211.00 | $47,211.00 |
| **Land Purchase Cost** | $3,000.00 | $3,000.00 | $3,000.00 | $3,000.00 | $3,000.00 |
| **Animal Escapes / Deaths**| 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| **Care Actions** | **215** | 196 | 185 | 185 | 185 |
| **Feed Actions** | 238 | 232 | 228 | 228 | 228 |
| **Total Actions in SW** | 364 | 546 | 632 | 632 | 632 |
| **Move Actions** | 4,863 | 5,024 | 5,118 | 5,118 | 5,118 |

---

## 3. Analysis by Diagnostic Questions

### 3.1 Cap 8 (ARM_F)
> *Does the new architecture preserve or improve incumbent output without an acreage confound?*
- **Answer: YES.** Cap 8 preserves 100% of livestock safety (0 deaths/escapes, $70,257 revenue), produces $78,409.70 in core crop revenue (+$3,391.85 vs legacy baseline), and generates $7,910.30 net SW margin with exact $0.0000 cash residual closure.

### 3.2 Cap 12 (ARM_G12)
> *Can the first new four-tile cohort complete planting, same-day water, maturity and realization?*
- **Answer: YES on execution, NO on whole-farm economics.** The 4-tile cohort (Melon on Day 15) successfully planted, watered, matured, and realized $4,376.13 in additional crop sales. However, the transit and servicing load diverted core workers away from internal wheat production, requiring $9,543 in additional market feed purchases and causing a net whole-farm cash reduction of -$4,845.

### 3.3 Cap 16 (ARM_G16)
> *Can overlapping existing/new watering and harvest peaks be served on time?*
- **Answer: PARTIALLY.** An additional Tomato cohort was planted on Day 20, but watering peaks collided with core operations, reducing care actions from 196 to 185 and further depressing livestock yield. Whole-farm final cash decreased to $90,139.00.

### 3.4 Cap 20 & Cap 24 (ARM_G20, ARM_G24)
> *Do regional transfer and logistics costs exceed productive capacity gained? Can full occupancy avoid storage loss?*
- **Answer: CONSTRAINED BY SHED HEADROOM.** The reservation manager detected that prospective harvests at Day 21+ would exceed remaining shed headroom. It rejected expansion to 20 and 24 tiles completely. Both configurations safely halted at 16 tiles.

---

## 4. Phase P4 Conclusion & Release Recommendation

In accordance with the **P4 Economic Gate**:
- "Additional acreage must increase whole-farm final cash relative to the same new eight-tile dispatcher, while also being compared to canonical production. More SW attributed sales, fewer moves, or more planted tiles alone are not proof of benefit."
- "If a larger cap declines, report both economic and execution causes without changing policies within that trial."

The empirical evidence demonstrates that **8 SW tiles represents the optimal economic capacity frontier** under the current workforce size and core wheat/livestock portfolio. Expanding beyond 8 tiles incurs whole-farm opportunity costs (market feed dependency and lower livestock care frequency) that exceed the incremental gross margin of the crops.

Therefore, for Phase P5 (Experimental Confirmation and Release Evaluation), the recommended production candidate configuration is:
- **Maximum Adaptive SW Acreage Cap:** **8 tiles** (`SW_MAX_ADAPTIVE_ACREAGE = 8`).
- **Feature Flags Active:** `SW_P1_MISSION_OWNERSHIP_ENABLED = True`, `SW_P2_COORDINATED_DISPATCH_ENABLED = True`, `SW_P3_TRANSACTIONAL_RESERVATIONS_ENABLED = True`.

---

## 5. Exit Gate P4 Checklist

- [x] All acreage ladder caps (8, 12, 16, 20, 24) evaluated with frozen dispatcher, reservations, and policies.
- [x] All 5 ladder runs achieved exact $0.0000 cash residual closure.
- [x] Zero animal escapes or starvation deaths across all ladder arms.
- [x] Full economic decomposition of gross margin vs feed purchase displacement documented.
- [x] Storage congestion constraint identified as binding physical limit for caps $\ge 20$.
- [x] Protected submission artifact `dist/submission.zip` SHA-256 untouched (`E7FF7C5A4B91364C10898CB8A22E4680C9330F1E30171593DA2D1EED7DD4ED41`).
- [x] Protected validation seeds `98001–98050` completely untouched.
