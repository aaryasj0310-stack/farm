# SW economic model

Date: 2026-09-23. Figures are engine arithmetic or sensitivity estimates, not tournament results.

The P6 baseline panel (seeds 96401-96410, five opponents, both seats) averaged $101,035.79 final cash. P4.2, P6 and P6.1 are separate panels. Whole-farm cash closes as opening cash + actual sales - actual purchases. Regional revenue attribution requires tagged lots or a declared FIFO convention because shed inventory is fungible.

The reproducible model in artifacts/sw_economics/model.json uses engine SHA bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e. For the nominal D6 24-tile calendar, output is 96 melon, 32 strawberry, 160 wheat and 9 carrot, with $2,540 seeds, $2,000 land and $497 early-hire increment. Reference gross is $37,044.10; the subtotal after those explicit costs is $32,007.10 before core displacement, later wages, feed, slippage, storage and routing.

| Architecture | Weak | Moderate | Strong |
|---|---:|---:|---:|
| A selective crop, two late sheep deferred | $4,809 | $10,406 | $14,529 |
| B same crop, 14 hands from D11 | -$743 | $7,587 | $11,523 |
| C feed wheat + terminal carrots | $4,955 | $7,456 | $13,613 |
| C+ plus two D10 cows | $5,557 | $16,884 | $25,961 |

These are whole-farm stock-price sensitivities under preserved-core assumptions and fixed quantities. They are not confidence intervals. C+ adds 42 milk and 36 fertilizer but also 130 direct animal actions and $800 purchase cost; it can be infeasible without pasture and labor.

A waterfall is: incremental SW sales + verified feed substitution + core recovery - land - seeds - wages - lost retired-cohort output - routing, storage and price effects. Do not count wheat sold and the same wheat saved as feed twice. For B, two extra hands cost $11,590 from D11-D29. For C, credit only dated feed purchases actually displaced. For C+, charge animal care, placement, feed and market effects.

Cash-threshold purchase ignores labor and dated commitments. Current-turn feasibility is safer but misses launch preparation. Forward commitment is the only policy that coordinates hires, seed tranches, feed reserves, land and sales; it must cancel or downsize safely when its certificate fails.

Against the P6 baseline, $130,000 requires $28,964.21 more final cash. A does not close that gap in modeled cases; B is wage-dominated; C+ approaches it only in a strong, unvalidated case. No land purchase or leader replay proves the target.

