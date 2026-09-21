# P1.3-A: Isolated SW Generic Planting Gate — Balanced Three-Arm Results

- Control SHA: `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`
- P1.2 SHA: `4a2bd867cbd3184c77f9e7c38a768fae0a01f6cd`
- P1.3-A source HEAD: `18740e0e6b2c02bd547b411eb08214edb03acbd4`
- P1.3-A worktree fingerprint: `9591f5a06fa3531329fdd9a150f16651808218313dcb9455e7e48219a47b9b5d`
- Engine: 1.32.7
- Matched cases: 40/40
- Engine errors: 0

| Metric | Control | P1.2 | P1.3-A |
|---|---:|---:|---:|
| Mean final score | 101,387.12 | 91,733.23 | 93,713.18 |
| Confirmed SW acquisition cases | 0 | 31 | 31 |
| Starvation observations | 435 | 1346 | 1298 |
| NW+NE HARVEST attempts | 10399 | 9436 | 9550 |
| NW+NE unwatered EOD | 5560 | 7608 | 7499 |
| SW pasture plants confirmed from next observation | 0 | 466 | 0 |
| SW pasture active plant-days | 0 | 1835 | 0 |
| SW soil active plant-days | 0 | 2510 | 3453 |
| SW wheat HARVEST attempts | 0 | 692 | 476 |
| Wheat purchase units ordered | 34133 | 41531 | 42640 |
| Scheduler travel | 176357 | 179496 | 179631 |
| SW idle anchor assignments | 0 | 0 | 1 |
| Generic SW gate checks | 0 | 0 | 12098 |

## Matched scores

- p13_vs_p12: mean $1,979.95; median $861.50; SD $3,315.65; 95% CI [$919.55, $3,040.35]; 22W/9T/9L (N=40).
- p13_vs_control: mean $-7,673.95; median $-7,020.50; SD $10,253.30; 95% CI [$-10,953.11, $-4,394.79]; 6W/0T/34L (N=40).
- p12_vs_control: mean $-9,653.90; median $-10,460.00; SD $10,886.23; 95% CI [$-13,135.49, $-6,172.31]; 6W/0T/34L (N=40).

## Interpretation guardrails

- Only the generic SW planting gate differs between P1.2 and P1.3-A.
- Harvest/plant action counters are attempts; confirmed planting is measured from next observations.
- Excluded generic SW empty tiles are repeated decision opportunities, not unique successful plantings.
- All non-purchasing cases remain in the paired denominator.
- Do not merge on the basis of this screen alone.
