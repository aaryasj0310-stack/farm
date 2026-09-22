# P5.0 Idle Tile-Day Accounting & Slack Opportunity

## Physical 50-Tile Slack Census

Across the 100-game dataset, exactly **19,814 tile-days** were recorded in the `EMPTY` state (198.1 per game).

| Idle Category | Criteria | Total Days | Per Game | Economic Recoverability |
| :--- | :--- | :---: | :---: | :--- |
| **E1: Terminal Season** | Day ≥ 27 empty tiles | **6,555** | **65.5** | **UNRECOVERABLE**: No crop can mature in ≤ 3 days |
| **E2: Capital Constrained** | Farm money < $10 | **0** | **0.0** | **NON-EXISTENT**: Agent maintains ample treasury |
| **E5: Recoverable Slack** | Day ≤ 26 empty cultivable tiles | **13,259** | **132.6** | **HIGHLY RECOVERABLE**: Idle capacity awaiting orders |

---

## Anatomy of E5 Recoverable Slack (132.6 Days/Game)

Why do 132.6 cultivable tile-days remain empty during the active season?
1. **Post-Harvest Dig Delay**: When a crop is harvested, the tile remains in `EMPTY` status for 1–3 days before the central planner issues a new `PLANT` mission.
2. **NE Staging Inertia**: After the NE quadrant is unlocked (Day 8–11), 3–5 tiles remain unplanted for multiple days while workers prioritize watering existing NW crops.
3. **Shed Access Staging Buffer**: Tiles near $(4,4)$ are often left unseeded because the scheduler avoids planting adjacent to high-transit routes.

### Economic Value of Recovering E5 Slack (T4 Opportunity)
Converting just **10–15% of E5 recoverable slack** into fast 3-day Carrot cycles yields an estimated **+$500.00 per game**.
