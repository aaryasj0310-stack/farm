# SW labor and capacity model

The current schedule is 4 hands on days 0-5, 8 on days 6-9, 10 on day 10, and 12 on days 11-29. Daily hire costs are Fibonacci: 4=$7, 8=$54, 10=$143, 12=$376, 13=$609, 14=$986, 15=$1,596. Hires act only after their purchase turn and reset at midnight; two extra hands from day 11 through day 29 cost $11,590.

The old P6 hourly action map is invalid because its harness recorded daily activity at hour 0. The replacement diagnostic under simulations/results/sw_architecture_audit patches engine execution functions and verifies cash closure. episodeSteps=720 ends at day 29 hour 22.

| Crop | Units | Occupied days | Direct actions | Reference net |
|---|---:|---:|---:|---:|
| Wheat | 4 | 5 | 6 | $90 |
| Carrot | 3 | 4 | 5 | $85 |
| Melon | 6 | 11 | 10 | $1,420 |
| Tomato | 4 | 12 | 8 | $190 |
| Strawberry | 4 | 17 | 10 | $380 |

Tomato and strawberry have four production ticks, not unlimited repeats. The nominal 24-tile calendar starts cohorts on days 6, 7 and 8, producing 96 melon, 32 strawberry, 160 wheat and 9 terminal carrot; seeds cost $2,540 and direct operations total 495. A planning allowance of 30 movement plus 8 deposit actions per harvest day gives 1,351 planned actions and a lower bound of three SW workers; this is not a routing result and does not reserve core work.

P4.1 reserved two productive workers for eight SW tiles. Their core agricultural attempts fell 141.0 to 29.4 per game, SW attempts reached 129.9, core watering compliance fell 4.45 points, and final cash fell $4,819.10/game. It proves exclusive transfer is unsafe, but not the old crop-death or direct-profit decomposition.

Declining two late D14 sheep saves an ideal 102 direct operations, 30 feed wheat and $800 animal cost, but loses 36 wool and 28 fertilizer. Those savings occur late and cannot fund a D6 launch. Earlier hires add $497 in the nominal calendar; hiring 14 rather than 12 from day 11 costs ,590.

| Phase | Binding constraint | Protect |
|---|---|---|
| Days 0-5 | Bootstrap cash and wage/seed timing | first crop cash and NE escrow |
| Days 6-10 | Planting, paired watering, NE service and SW launch | launch-hour workers and feed staging |
| Days 11-15 | Three-region maintenance and first harvest peaks | core deadlines and shed headroom |
| Days 16-20 | Concurrent harvest, routing and market work | harvest-before-decay and price-aware sales |
| Days 21-29 | Terminal rotations and inventory congestion | only dated profitable cohorts |

The next planner needs a time-indexed certificate containing mandatory tasks, regional slots, feed carriers, shed capacity, harvest deadlines and marginal cash.


