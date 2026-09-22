# P5.0 Within-Core Realized Tile Value & Occupancy Heatmap

## Denominator Accounting: Physical 50 Tiles vs Policy 46 Tiles

A critical methodological invariant established in P5.0 is the **physical 50-tile denominator**:
- **Northwest (NW) Quadrant**: $5 \times 5 = 25$ physical tiles, coordinates $(0,0)$ to $(4,4)$.
- **Northeast (NE) Quadrant**: $5 \times 5 = 25$ physical tiles, coordinates $(5,0)$ to $(9,4)$.
- **Total Physical Core Capacity**: **50 tiles**.

### Policy Usable Denominator
The shed structure is not an engine structure tile, but physical transit rules require clear shed access corridors at $(4,4)$ and $(5,4)$:
- **Shed Access Staging Tiles**: $(4,4)$ and $(5,4)$ (2 tiles).
- **True Policy-Cultivable Core Capacity**: $50 - 2 = $ **46 tiles** (or 48 when staging is transient).

---

## Occupancy Aggregation Across the Core (150,000 Tile-Days)

| Occupancy State | NW Core (Tile-Days) | NE Core (Tile-Days) | Shed Access (Tile-Days) | Cultivable Core (Tile-Days) | Total Core Share (%) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `PLANT_WHEAT` | 22,819 | 17,247 | 404 | 39,662 | 26.7% |
| `PLANT_STRAWBERRY` | 4,539 | 18,377 | 1,394 | 21,522 | 15.3% |
| `PLANT_MELON` | 15,591 | 694 | 945 | 15,340 | 10.9% |
| `PLANT_TOMATO` | 4,416 | 948 | 1,308 | 4,056 | 3.6% |
| `PLANT_CARROT` | 1,617 | 6,406 | 270 | 7,753 | 5.3% |
| `ANIMAL_COW` | 11,933 | 3,201 | 0 | 15,134 | 10.1% |
| `ANIMAL_SHEEP` | 3,551 | 4,688 | 0 | 8,239 | 5.5% |
| `EMPTY` (Idle) | 10,534 | 10,439 | 1,159 | 19,814 | 14.0% |
| `LOCKED` (Pre-Unlock) | 0 | 13,000 | 520 | 12,480 | 8.7% |

---

## Spatial & Operational Insights

1. **Zonal Specialization**:
   - NW is heavily focused on early livestock (Cows: 11,933 tile-days) and high-value initial Melon rotations (15,591 tile-days).
   - NE serves as the mid-to-late season expansion hub, dominated by multi-flush Strawberry orchards (18,377 tile-days) and quick-cycle Carrots (6,406 tile-days).
2. **Shed Access Contention**:
   - The shed access coordinates $(4,4)$ and $(5,4)$ were erroneously cultivated for 4,321 tile-days across the season, causing transit collisions and worker detours during peak morning delivery windows.
3. **Idle Land Slack**:
   - 19,814 cultivable tile-days remained `EMPTY` across the season (132.6 recoverable tile-days per game), representing substantial unharvested capacity.
