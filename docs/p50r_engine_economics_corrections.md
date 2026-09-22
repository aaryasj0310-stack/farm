# P5.0-R Engine Economics Corrections & Authoritative Constants

## Ground-Truth Engine Parameters Verified from `kaggriculture.py`

Before conducting any counterfactual modeling, all crop, animal, lifecycle, and spatial constants were verified directly against the running competition simulation engine (`kaggle_environments.envs.kaggriculture.kaggriculture`). 

This document formally records these verified constants and corrects the errors present in the preliminary P5.0 reports.

---

## 1. Crop Constants & Maturation Mechanics

| Parameter | WHEAT (Engine Ground Truth) | WHEAT (Prior P5.0 Claim) | CARROT (Engine Ground Truth) | CARROT (Prior P5.0 Claim) |
| :--- | :---: | :---: | :---: | :---: |
| **Seed Cost** | **$10.00** | $20.00 *(Error)* | **$20.00** | $35.00 *(Error)* |
| **Crop Type** | One-time (`ongoing: False`) | One-time | One-time (`ongoing: False`) | One-time |
| **First Yield Age** | **2 days** | 2 days | **2 days** | 2 days |
| **Max Yield Age** | **4 days** | 5 days *(Error)* | **3 days** | 3 days |
| **Bonus Window Start** | `(4 + 1) // 2 = ` **Day 2** | Day 2 | `(3 + 1) // 2 = ` **Day 2** | Day 2 |
| **Bonus Window Days** | **Days $P+2, P+3, P+4$** (3 days) | 4 days | **Days $P+2, P+3$** (2 days) | 2 days |
| **Max Unfertilized Yield** | **4 units** ($1 + 1 + 1 + 1$) | 6 units *(Error)* | **3 units** ($1 + 1 + 1$) | 2 units *(Error)* |
| **Max Fertilized Yield** | **6 units** ($\min(6, 1 + 2 + 2 + 2)$)| 6 units | **4 units** ($\min(4, 1 + 2 + 2)$) | 4 units |
| **Decay Step (`mls`)** | `(P + 5) * 24` (Day $P+5$ H0) | Day $P+6$ | `(P + 4) * 24` (Day $P+4$ H0) | Day $P+4$ |
| **Target Harvest Day** | **Day $P+4$** (4-day cycle) | 5-day cycle *(Error)* | **Day $P+3$** (3-day cycle) | 3-day cycle |

### Detailed Engine Lifecycle Trace
1. **Wheat (`max_yield_day = 4`, `max_yield = 6`)**:
   - Planted on Day $P$: Starts with `yield_units = 1` and `consecutive_unwatered = 1`. Requires watering on Day $P$ to avoid dying into a weed overnight.
   - Day $P+1$: Watering resets `consecutive_unwatered = 0`, but adds 0 bonus (`age = 1 < window_start = 2`).
   - Day $P+2$: Watering adds $+1$ bonus (or $+2$ if fertilized). Unfertilized yield reaches 2.
   - Day $P+3$: Watering adds $+1$ bonus (or $+2$ if fertilized). Unfertilized yield reaches 3.
   - Day $P+4$: Watering adds $+1$ bonus (or $+2$ if fertilized). Unfertilized yield reaches **4 units** (fertilized reaches **6 units**). Immediately after watering, wheat is at its maximum yield and must be harvested on Day $P+4$.
   - Day $P+5$ Hour 0: Lifespan step `(P + 5) * 24` begins. `tile["yield_units"]` decays by 1 unit every 2 steps until becoming a WEED.

2. **Carrot (`max_yield_day = 3`, `max_yield = 4`)**:
   - Planted on Day $P$: Starts with `yield_units = 1`. Requires watering on Day $P$.
   - Day $P+1$: Watering adds 0 bonus (`age = 1 < window_start = 2`).
   - Day $P+2$: Watering adds $+1$ bonus (or $+2$ if fertilized). Unfertilized yield reaches 2.
   - Day $P+3$: Watering adds $+1$ bonus (or $+2$ if fertilized). Unfertilized yield reaches **3 units** (fertilized reaches **4 units**). Harvested on Day $P+3$.
   - Day $P+4$ Hour 0: Lifespan step begins decay.

---

## 2. Animal Constants & Feed Obligation Semantics

| Parameter | COW (Engine Truth) | SHEEP (Engine Truth) | GOOSE (Engine Truth) |
| :--- | :---: | :---: | :---: |
| **Purchase Cost** | **$400.00** | **$500.00** *(P5.0 cited $300)* | **$300.00** |
| **Structure Required** | PASTURE ($0 build) | PASTURE ($0 build) | COOP ($0 build) |
| **Product** | MILK (Base $160) | WOOL (Base $200) | EGG (Base $50) |
| **First Yield Day** | Day 8 | Day 6 | Day 4 |
| **Production Interval** | Every 2 days | Every 3 days | Every 1 day |
| **Max Stored Yield** | 6 units | 6 units | 4 units |
| **Daily Feed Type** | 1 Wheat | 1 Wheat | None (Coop) |
| **Starvation Limit** | Escapes after 2 consecutive unfed days | Escapes after 2 consecutive unfed days | N/A |

### Feed Obligation Termination at Day 28
In `kaggriculture.py`, daily refresh at the end of Day 28 transitions into Day 29. 
- Feeding an animal on Day 28 triggers product generation at EOD, which can be collected and sold during Day 29.
- Feeding an animal on Day 29 generates product at the end of Day 29 (Step 720), which is the final game step; that product can never be collected or sold.
- Therefore, in authoritative baseline behavior, **all feeding obligations end after Day 28**.
- Any feed projection using `(30 - day)` erroneously counted Day 29 (and Day 30), artificially inflating perceived feed deficits by 1–2 days of herd consumption.

---

## 3. Core Capacity & Denominator Correction

| Concept | Correct Value | Prior P5.0 Statement | Reconciliation |
| :--- | :---: | :---: | :--- |
| **Physical Core Tiles** | **50 tiles** | 50 tiles | NW ($5 \times 5 = 25$) + NE ($5 \times 5 = 25$) |
| **Shed Staging Corridors** | **2 tiles** | 4 tiles *(implied)* | Coordinates $(4,4)$ and $(5,4)$ adjacent to shed |
| **Policy-Cultivable Capacity**| **48 tiles** | 46 tiles *(Error)* | $50 - 2 = \mathbf{48\text{ tiles}}$. Prior 46 double-counted two staging borders. |

---

## 4. Key Takeaway for P5.0-R

Every economic calculation in P5.0-R uses these exact engine constants:
- Wheat seed: **$10**
- Carrot seed: **$20**
- Wheat unfertilized yield: **4 units** (not 6)
- Carrot unfertilized yield: **3 units** (not 2)
- Wheat maturation: **4 days** (Day $P \rightarrow P+4$)
- Carrot maturation: **3 days** (Day $P \rightarrow P+3$)
- Feed cutoff: **Day 28**
- Core cultivable capacity: **48 tiles**
