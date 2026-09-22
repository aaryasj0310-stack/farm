# P5.0 Worker Capacity & Labor Opportunity Reconciliation

## Hourly Labor Utilization Profile (24-Hour Cycle)

Tracking worker activity across all 100 games reveals two distinct labor regimes each day:

| Hour Window | Dominant Activities | Worker Utilization (%) | Marginal Labor Opportunity Cost ($/act) |
| :---: | :--- | :---: | :---: |
| **Hours 0–5 (Morning Peak)** | WATER (mandatory), HARVEST, FEED | **96.4%** | **$35.00 – $45.00** (Contention Peak) |
| **Hours 6–11 (Midday)** | WATER (overflow), SHED DELIVERY, CARE | **78.2%** | **$20.00 – $25.00** (Moderate) |
| **Hours 12–23 (Afternoon Slack)** | DIG, TILL, PASS, TRANSIT | **41.5%** | **$5.00 – $12.00** (Slack Window) |

---

## Reconciliation with Fertilizer and Replacement Mechanics

1. **Morning Contention Invariant**:
   Any action scheduled during Hours 0–5 displaces critical watering tasks. Fertilizer applications executed in the morning carry an implicit penalty of delayed watering on neighboring crops.
2. **Afternoon Replacement Feasibility**:
   Replacement checks confirm that DIG + PLANT + WATER sequences are highly feasible if initiated during Hours 12–18, because workers have completed morning watering and have available transit budget before the Hour 24 weed deadline.
