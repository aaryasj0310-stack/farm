# SW P1.1 Responsive Scheduler — Balanced Three-Arm Results

- Control SHA: `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`
- P1 SHA: `b89c8381b341d43c9e81e0701fd8d39edbc8aaaa`
- P1.1 SHA: `b44a1d2f754bc6ecb66077033a2bf44350146bab`
- Engine: `1.32.7`
- Balanced cases: 40 per arm (20 seeds × 2 seats)

## Aggregate results

| Metric | Control | P1 | P1.1 |
| --- | ---: | ---: | ---: |
| Mean score | USD 101,387.12 | USD 81,542.73 | USD 92,596.57 |
| Confirmed SW acquisitions | 0 | 32 | 31 |
| Starvation observations | 435 | 1137 | 1447 |
| NW+NE unwatered EOD | 5560 | 8578 | 7721 |
| NW+NE harvest executions | 10399 | 8150 | 9290 |
| SW home-unit turns | 0 | 0 | 20404 |
| SW anchor assignments | 0 | 0 | 0 |
| Travel distance | 176357 | 189635 | 179945 |

## Matched score deltas

- **P1 - Control:** mean USD -19,844.40, median USD -21,953.00, 95% CI [-23,998.54, -15,690.26], 0W/8T/32L.
- **P1.1 - Control:** mean USD -8,790.55, median USD -9,553.50, 95% CI [-11,891.45, -5,689.65], 6W/0T/34L.
- **P1.1 - P1:** mean USD 11,053.85, median USD 12,034.00, 95% CI [6,000.81, 16,106.89], 31W/0T/9L.

## Guardrails

- P1.1 changes scheduler home-zone allocation only; MacroPlanner SW activation remains unchanged.
- SW land cost is USD 2,000.
- Harvest counts are executed HARVEST actions, not provenance-traced SW revenue.
- Purchasing and non-purchasing cases remain in the denominator.
- This is a causal screen, not an automatic production promotion.
