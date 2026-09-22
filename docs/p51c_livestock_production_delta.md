# Kaggriculture P5.1-C — Livestock Production Lifecycle Delta

## 1. Executive Summary

This report establishes the precise causal mechanism by which the P5.1 Two-Cycle Carrot Rotation destroyed **−$985.32 in livestock revenue**, accounting for **96.5%** of the panel-wide **−$1,020.68** deficit.

Across all 100 matched pairs (200 live games), livestock telemetry tracked animal placement, feeding, caring, production events, unit yields, harvest collection, and escapes for Cow, Sheep, and Goose enterprises.

### Core Discoveries:
1. **Zero Animal Escapes**:
   - Both Control and Treatment achieved **0.00 escapes** across all 200 games.
   - The livestock deficit was NOT caused by animal loss, fence breaks, or death.
2. **Production Events Remained Identical, But Yield Per Event Collapsed**:
   - Total Cow production events were identical: **54.16 vs 54.16**.
   - Total Sheep production events were identical: **21.86 vs 21.86**.
   - However, milk units produced dropped by **−2.50 units** (173.59 $\rightarrow$ 171.09).
   - Wool units produced dropped by **−1.91 units** (84.53 $\rightarrow$ 82.62).
3. **The Root Mechanism: Lost Care Bonuses and Unfed Reset**:
   - In Kaggriculture game engine mechanics (`_daily_refresh_animals`):
     - An animal produces `base_yield + pending_care_bonus` **only if `fed_today` is true**.
     - If an animal is cared for but goes unfed on the production day, the care bonus is completely voided (`bonus = 0 if not fed_today`).
   - Treatment suffered **−1.72 fewer cow feeds** and **−1.47 fewer sheep feeds**, which voided care bonuses and depressed total yields.
4. **Extreme Leverage of Livestock Unit Values**:
   - Forfeiting just **1.62 harvested milk units** and **1.55 harvested wool units** destroyed:
     - Milk Revenue: **−$404.58** ($244.08/unit average)
     - Wool Revenue: **−$545.65** ($214.82/unit average)
     - Fertilizer Revenue: **−$35.09** ($81.10/unit average)
     - **Total Livestock Deficit: −$985.32**

---

## 2. Livestock Lifecycle Telemetry Table

The table below presents the panel-wide mean values per game across all 100 matched pairs:

| Species | Lifecycle Metric | Control Mean | Treatment Mean | Treatment − Control ($\Delta$) | Economic Impact |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **COW** | Placed Animals | 6.88 | 6.88 | **0.00** | Identical herd size |
| | Feed Events (`FEED_COW`) | 142.56 | 140.84 | **−1.72** | Skipped feeds due to grain stockouts |
| | Care Events (`CARE_COW`) | 126.81 | 125.83 | **−0.98** | Skipped care |
| | Production Intervals | 54.16 | 54.16 | **0.00** | Timing intact |
| | **Milk Units Produced** | **173.59** | **171.09** | **−2.50** | Voided care bonuses |
| | Harvest Collection Events | 48.13 | 48.16 | **+0.03** | Collection intact |
| | **Milk Units Harvested** | **149.50** | **147.88** | **−1.62** | Forfeited milk |
| | Escapes | 0.00 | 0.00 | **0.00** | Zero escapes |
| | Surviving End Count | 6.86 | 6.86 | **0.00** | Full herd preserved |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **SHEEP** | Placed Animals | 4.39 | 4.39 | **0.00** | Identical flock size |
| | Feed Events (`FEED_SHEEP`)| 73.85 | 72.38 | **−1.47** | Skipped feeds due to grain stockouts |
| | Care Events (`CARE_SHEEP`)| 70.95 | 70.40 | **−0.55** | Skipped care |
| | Production Intervals | 21.86 | 21.86 | **0.00** | Timing intact |
| | **Wool Units Produced** | **84.53** | **82.62** | **−1.91** | Voided care bonuses |
| | Harvest Collection Events | 19.60 | 19.54 | **−0.06** | Collection intact |
| | **Wool Units Harvested** | **76.23** | **74.68** | **−1.55** | Forfeited wool |
| | Escapes | 0.00 | 0.00 | **0.00** | Zero escapes |
| | Surviving End Count | 4.38 | 4.38 | **0.00** | Full flock preserved |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **GOOSE** | All Metrics | 0.00 | 0.00 | **0.00** | Unused by strategy |

---

## 3. The Transmission Chain: Why Grain Depletion Collapsed Livestock

The causal chain from wheat replacement to livestock revenue loss is direct and unambiguous:

```
+13.29 Carrot Plantings replacing Wheat
  │
  ▼
-41.84 Farm-Grown Wheat Harvested (Days 21-27)
  │
  ▼
Temporary Intraday Grain Depletion in Shed
  │
  ▼
Feeding Workers Encounter Empty Shed Before Market Orders Fill
  │
  ▼
-1.72 Cow Feeds & -1.47 Sheep Feeds Skipped on Critical Production Days
  │
  ▼
Care Bonuses Voided in Engine (_daily_refresh_animals)
  │
  ▼
-2.50 Units Milk & -1.91 Units Wool Lost
  │
  ▼
-$404.58 Milk Rev + -$545.65 Wool Rev + -$35.09 Fert Rev = -$985.32 CASH LOSS
```

### Why Buying Feed Wheat Could Not Prevent the Loss:
The agent attempted to compensate by purchasing **$559.88** more feed wheat from the town market. However:
1. Market purchases execute at the end of the turn during `_process_market`.
2. Feeding tasks assigned in the morning hours (Hours 0–6) require wheat physically present in the shed or worker backpack *at the start of the task*.
3. When local wheat ran dry, workers assigned to feed animals were blocked, skipping the feed for that turn or day.
4. Thus, Treatment spent $559.88 buying replacement wheat *and still missed feeds*, suffering a double penalty: higher feed expense **plus** collapsed product yield.
