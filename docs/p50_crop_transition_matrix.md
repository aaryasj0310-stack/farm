# P5.0 Crop State Transition Matrix & Rotational Dynamics

## State Transition Probabilities (Day $t \rightarrow t+1$)

| From State | To `EMPTY` | To `PLANT_WHEAT` | To `PLANT_CARROT` | To `PLANT_STRAWBERRY` | To `PLANT_MELON` | To `STRUCTURE` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`EMPTY`** | 68.2% | 14.1% | 6.5% | 7.2% | 3.8% | 0.2% |
| **`PLANT_WHEAT`** | 16.4% (harvested) | 83.6% (growing) | 0.0% | 0.0% | 0.0% | 0.0% |
| **`PLANT_CARROT`** | 33.1% (harvested) | 0.0% | 66.9% (growing) | 0.0% | 0.0% | 0.0% |
| **`PLANT_STRAWBERRY`**| 2.1% (dug) | 0.0% | 0.0% | 97.9% (growing/flush)| 0.0% | 0.0% |
| **`PLANT_MELON`** | 12.5% (harvested) | 0.0% | 0.0% | 0.0% | 87.5% (growing) | 0.0% |
| **`STRUCTURE`** | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% (permanent)|

---

## Rotational Friction Analysis

The transition matrix reveals substantial **rotational friction**:
- Once a tile becomes `EMPTY`, there is a **68.2% daily probability** that it remains `EMPTY` on the following day!
- In an optimal rotation, an empty tile should be replanted within 24 hours (transition probability to `EMPTY` < 15%).
- Tightening the mission dispatch loop to plant immediately upon harvesting will drastically compress this idle phase.
