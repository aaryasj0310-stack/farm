# SW P1.2 Serviceability-Aware Activation — Balanced Four-Arm Results

- Control SHA: `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`
- P1 SHA: `b89c8381b341d43c9e81e0701fd8d39edbc8aaaa`
- P1.1 SHA: `b44a1d2f754bc6ecb66077033a2bf44350146bab`
- P1.2 SHA: `4a2bd867cbd3184c77f9e7c38a768fae0a01f6cd`
- Engine: `1.32.7`
- Balanced cases: 40 per arm (20 seeds × 2 seats)

## Aggregate results

| Metric | Control | P1 | P1.1 | P1.2 |
| --- | ---: | ---: | ---: | ---: |
| Mean score | USD 101,387.12 | USD 81,542.73 | USD 92,596.57 | USD 91,733.23 |
| Confirmed SW acquisitions | 0 | 32 | 31 | 31 |
| Starvation observations | 435 | 1137 | 1447 | 1346 |
| NW+NE unwatered EOD | 5560 | 8578 | 7721 | 7608 |
| NW+NE harvest executions | 10399 | 8150 | 9290 | 9436 |
| SW home-unit turns | 0 | 0 | 20404 | 19128 |
| SW anchor assignments | 0 | 0 | 0 | 0 |
| Travel distance | 176357 | 189635 | 179945 | 179496 |
| Activation blocked turns | 0 | 0 | 0 | 684 |

## Matched score deltas

- **P1 - Control:** mean USD -19,844.40, median USD -21,953.00, 95% CI [-23,998.54, -15,690.26], 0W/8T/32L.
- **P1.1 - Control:** mean USD -8,790.55, median USD -9,553.50, 95% CI [-11,891.45, -5,689.65], 6W/0T/34L.
- **P1.2 - Control:** mean USD -9,653.90, median USD -10,460.00, 95% CI [-13,135.49, -6,172.31], 6W/0T/34L.
- **P1.2 - P1.1:** mean USD -863.35, median USD 0.00, 95% CI [-2,058.48, 331.78], 14W/9T/17L.
- **P1.2 - P1:** mean USD 10,190.50, median USD 10,513.50, 95% CI [4,822.79, 15,558.21], 30W/0T/10L.

## Guardrails

- P1.1 changes scheduler home-zone allocation only; MacroPlanner SW activation remains unchanged.
- P1.2 adds only serviceability-aware SW activation on top of P1.1.
- SW land cost is USD 2,000.
- Harvest counts are executed HARVEST actions, not provenance-traced SW revenue.
- Purchasing and non-purchasing cases remain in the denominator.
- This is a causal screen, not an automatic production promotion.
