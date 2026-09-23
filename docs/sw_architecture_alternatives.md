# Complete SW-capable farm architectures

Date: 2026-09-23. Source baseline: `975da5e1683f1bb57463cb9478344d0acf379d58`. All alternatives below are **unimplemented counterfactual designs**. Neither the arithmetic sensitivities nor leader replay scores are tournament improvements.

Read [historical audit](sw_architecture_deep_audit.md), [leader evidence](sw_leader_comparison.md), [labor model](sw_labor_and_capacity_model.md), and [economic model](sw_economic_model.md) together. Reproducible calculations are in `scripts/sw_economics_audit.py` and `artifacts/sw_economics/`. Some old reports call gross regional value profit; this document does not.

## Shared engine and safety constraints

- A quadrant is 25 tiles. These designs reserve one central access tile, leaving **24 planned agricultural tiles**; this reservation is a layout choice, not an engine prohibition on planting the 25th tile. Saved leaders sometimes plant all 25.
- SW is the second purchased quadrant and costs $2,000 after $1,000 NE. A nominal strategy unlock day in config is not an engine growth constraint.
- Hires expire every midnight. Rehire cost is Fibonacci: 8 hands $54/day, 10 $143, 12 $376, 13 $609, 14 $986, 15 $1,596. Count the farmer separately. A 13th hand costs $233 **each day**, a 14th another $377.
- Market orders do not consume a worker operation, but occupy one of ten orders per turn and settle after farm actions. PLANT reads global seeds; WATER does not require a refill trip. Feeding and fertilization require inventory on the acting worker.
- Existing animals remain fed. Reducing a herd means declining a future purchase, not starving or assuming a nonexistent profitable animal resale. Preserve accessible feed before any crop substitution.
- Tomato/strawberry each have four production ticks, not unlimited repeats through the season. Unfertilized wheat/carrot/melon caps are 4/3/6; care and fertilizer have precise timing. Monetary crop rankings without harvest calendars are insufficient.
- Terminal produce must be harvested, delivered, and sold during an actual playable market turn. Pin the harness horizon: the current diagnostic `episodeSteps=720` run ends at step 718 (D29 H22), not a presumed H23 sale.

## A. Crop-led expansion with selective core substitution

**Economic thesis:** pay the low marginal wages earlier, preserve valuable established livestock and crop cohorts, and deliberately decline low-return *future* commitments to obtain a commercial SW portfolio. Replace fixed region ownership with deadline-aware regional service. This is not “remove four early animals.”

| Component | Complete proposed policy |
|---|---|
| NW role | Keep the initial wheat/bootstrap and first melon cash tranche; keep the physically needed feed wheat and established near-shed animals. Replant only against a feed/value certificate. |
| NE role | Preserve committed strawberry/tomato harvests and the early profitable herd. Before admitting later livestock or a replacement crop, compare its whole-farm marginal contribution with the SW schedule. |
| SW role | Commercial mixed production: nominal 8 melon, 8 strawberry, 8 wheat tiles, in adjacent cohorts of 3/3/2 tiles **of each crop** over three days. Wheat provides physical feed optionality, not a justification for selling the same units twice in the ledger. |
| Acquisition | Nominal arithmetic starts planting D6/D7/D8, so land and first seeds must be available by D6. A practical D7-D9 purchase is a different, smaller remaining-season opportunity and must be recalculated; no unchanged 96-melon forecast after a delay. |
| Workforce | 4 hands D0-D2, 8 D3-D5, 10 D6-D10, 12 D11 onward, with a farmer throughout. This earlier ramp adds $497 versus the fixed baseline. SW needs a proposed 2-3-worker service envelope, with three at modeled peaks; core keeps the remainder plus deadline-based sharing. No fictitious free extra workers. |
| Herd | Existing/admitted early animals retained and fed. A numerical substitution case declines two sheep otherwise placed D14; this is an illustrative marginal cohort, not evidence that two such purchases exist in every baseline game. Decline them only if their lost contribution is smaller than the enabled SW value. |
| Feed | Protect production-day and survival deliveries before discretionary seed/animal purchases. Own SW wheat can replace purchased or core-grown feed only after actual harvest and timely pickup are feasible. |
| Capital | $2,000 land + $1,520 initial seeds, staged $570/$570/$380, plus the $497 incremental early hiring and all baseline feed/hire commitments. Full-season SW seeds $2,540 in the D6 arithmetic calendar. A $300 cash floor alone is not enough. |
| Spatial design | Contiguous crop cohorts; retain livestock beside central access; assign a service route, not a permanent ID. Do not shuttle SW workers to NE for ordinary work while feasible local deadlines remain. Allow a globally capable worker to rescue an imminent feed/harvest deadline. |
| Priorities | Feed and crop survival; deadline-critical bonus water/harvest; profitable region launch with paired watering; scheduled fertilizer where incremental value exceeds its sale opportunity; nonurgent work last. Use deadlines/value, not a universal “care first” rule. |
| Timeline | Prepare money and crop commitments D0-D5; establish SW over three days; first wheat P+4; first melon P+10; strawberry production P+10/12/14/16; second melon only where its harvest and sale fit; terminal rotations only after a dated feasibility check. |
| Required changes | Persistent expansion commitment, exact crop cohort calendar, shared feed/cash/time holds, variable early hire target, selective livestock admission, regional deadline allocation and supply-aware sales. |

### A: explicit resource and cash waterfall

For the nominal D6 calendar, SW output is **96 melon + 32 strawberry + 160 wheat + 9 carrot**. Only the earliest three wheat tiles can complete the terminal carrot rotation; assuming 24 terminal carrots is a deadline error. Direct crop operations total 495. A deliberately explicit, unverified allowance of 30 movement actions per active day and eight deposit/logistics actions per harvest day gives **1,351 SW worker-actions**, with daily peak 68. This is a planning budget, not a routing proof.

Declining two D14 sheep saves $1,000 animal purchase, 30 feed wheat and 102 direct operations, but foregoes **36 wool and 28 collected fertilizer** in the ideal fed/cared engine calculation. Saved feed wheat is reflected once in the net market quantity; it is not also a separate purchase saving in the stock model. Seed costs are already in the net expense line. Pasture building consumes actions but has no monetary engine price in this calculation.

The labor waterfall is:

`baseline executable hours + earlier-hire hours + 102 saved sheep operations + verified saved routes - 1,351 SW actions - any other changed work`.

The sheep savings occur late, while SW needs launch labor early. Earlier hires do not provide free D16 harvest capacity. **This design has an unresolved capacity gap** until daily/hourly routing and preserved-core tasks fit together. Do not call the entire 1,351 actions displaced production: some can come from extra early hands or avoided travel, but those savings must be measured.

The whole-farm stock-price sensitivity subtracts land $2,000, seeds $2,540, hires $497, and credits the avoided $1,000 animal purchase. Net product changes include +190 wheat, +9 carrot, +32 strawberry, +96 melon, -36 wool, -28 fertilizer. It re-prices baseline output too. Results: **+$4,809 / +$10,406 / +$14,529** in the defined weak/moderate/strong inventory-demand cases. These are conditional sensitivities, **not a forecast interval**. Missing routing costs, lost core production or infeasible early financing can erase them.

**Failure conditions:** D6 financing requires sacrificing an early high-value animal/crop; removed sheep are not actually marginal; preserved-core deadlines cannot be met with 12 hands; extra melon supply loses more incumbent melon revenue; delayed purchase removes the second melon cycle; or terminal deliveries fail. A lower SW tile target must be re-costed against the same $2,000 land, not assumed proportionally profitable.

## B. Labor-scaled three-quadrant farm

**Economic thesis:** preserve the existing productive business and purchase real additional service capacity. This is the cleanest counterfactual for asking whether SW can pay its full support cost.

| Component | Complete proposed policy |
|---|---|
| NW / NE | Retain their baseline crop/animal admissions and feed obligations; preserve the measured productive core, not merely its tile count. |
| SW | Same commercial 8/8/8 cohort portfolio as A for a controlled economic comparison. |
| Land timing | Same nominal D6 commitment; recalculate delayed variants. Buy only when the coming harvest peaks as well as startup are funded. |
| Workforce | A's earlier 8/10 ramp, then **14 hands + farmer D11-D29**. Allocate approximately three workers to SW service at peaks, with the other twelve to core/shared infrastructure. This is still one fewer core worker than the fully hired baseline if all three SW workers are occupied. |
| Herd / feed | Retain baseline herd and feed safety. Do not credit saved animal purchases or reduced feed consumption. |
| Capital | A's land/seed commitments, plus $11,590 added D11-D29 wages and $497 earlier ramp = **$12,087 incremental hiring**. Reserve wages through the next reliable receipt, not just the purchase hour. |
| Scheduling | Stable daily regional routes; morning service allocation recomputed from actual cohorts and feed carriers; midday deadline rescue; peak-day hired capacity chosen before the deadline. |
| Implementation | Shared planner/certificates and regional scheduler as in A, plus a real marginal hiring evaluator and multi-turn hiring order reservation. No herd substitution mechanism required initially. |

### B: cash and labor waterfalls

Output and seed/land spending are the same as nominal A, but no lost sheep product or avoided sheep expense. Incremental cash in the same whole-farm stock cases: **-$743 / +$7,587 / +$11,523**. The only changed fixed economic input versus the no-substitution mixed crop plan is the wage schedule; this exposes the steep wage curve directly.

Two new hands hired in the second market batch add at most about **44 actual actions/day**, not 48: hands cannot act on their hire turn. Across 19 days, that is approximately 836 hours before terminal-horizon adjustments, compared with 1,351 modeled SW hours over the whole D6-D29 period. Early hiring supplies additional launch capacity, but daily deficits must still be tested. A 15th hand raises cost another $610/day; buying it throughout D11-D29 adds **$11,590 again**, which can remove this design's modeled gain. Model peak-only hires separately as `sum(marginal daily wage)`.

**Failure conditions:** the 14-hand schedule still misses three-region peak service, marginal product realization falls into the weak case, wage reserves compete with feed, or extra market candidates delay hire settlement. A favorable season average does not pay a D16 hourly deficit retroactively.

## C. Feed-integrated regional farm with conditional livestock expansion

**Economic thesis:** use SW for reliable grain and adjacent livestock logistics, reduce dependence on expensive/timing-sensitive feed purchases, and expand livestock only if its marginal feed, cash, labor and market impact all remain favorable.

| Component | Complete proposed policy |
|---|---|
| NW role | Early bootstrap crops and existing central livestock; preserve minimum accessible grain until SW output arrives. Only retire an NW wheat cohort if the dated SW delivery fully replaces its feed contribution. |
| NE role | Existing cash crops, existing sheep, and market diversification. Do not reduce NE output merely to report higher SW utilization. |
| SW role | 24 wheat tiles in three cohorts of 9/9/6, four dated rotations where possible, then carrots only on the earliest nine tiles. Concentrated routes serve grain production. |
| Timing | Nominal launch D6-D8; first wheat D10-D12. Purchase is conditional on the modeled feed arrival and four-cycle calendar, not merely cash above $2,000. |
| Herd | Base C retains the baseline herd. C+ considers two cows placed D10 **only into already available core pasture**; if that pasture does not exist or displaces crops, debit it and reduce production. Never assume 24 SW grain tiles and extra SW pasture occupy the same land. |
| Workforce | A's earlier ramp and 12-hand normal ceiling in the arithmetic case. Grain needs its own regional service envelope; added cows require their own demonstrated spare hours or explicitly priced hires. |
| Feed policy | Credit only units that actually displace a dated feed purchase or become additional net sales. Retain wheat stock/market fallback before first harvest. Treat harvest/price risk as a feed liability. |
| Capital | $2,000 land + $240 initial wheat seeds in tranches; full-season seeds $1,140; $497 earlier hire ramp. C+ adds $800 animals and their placement/staging costs in actions; reserve feed before their first output. |
| Priorities | Feed staging and animal deadlines, wheat bonus-water/harvest, manure/milk realization, then discretionary grain liquidation. Do not allow auto-selling newly harvested grain to invalidate the feed certificate. |
| Changes | Cohort-level feed ledger, wheat retention keyed to dated obligations, pasture/site checks, marginal species valuation, and geographically shared crop/animal routes. |

### C: cash and labor waterfalls

Base C produces **384 additional wheat and 27 carrots**, spending $1,140 seeds, $2,000 land and $497 additional hires. The stock-price cases yield **+$4,955 / +$7,456 / +$13,613**. This is not $384 times the historical average purchase quote: much historical wheat buying was later resold, and on-farm consumption is much smaller than total gross purchases. Surplus grain depresses sale prices; replacing purchases can also reduce market depletion and lower prices on incumbent wheat sales.

C+ adds ideal **42 milk and 36 fertilizer**, consumes 38 of those wheat units, and spends $800 cows. Its net-quantity case is +346 wheat, +27 carrot, +42 milk, +36 fertilizer. Whole-farm stock-price sensitivities become **+$5,557 / +$16,884 / +$25,961** before any missing support/core cost. In the weak milk case, extra milk adds almost no whole-farm sales cash because it depresses price on existing milk. This demonstrates why “more cows” is not automatically profitable.

Those two D10 cows require **130 extra direct actions** before travel and feed staging. Base grain already requires **621 direct operations**. Adding animals while retaining a 12-hand ceiling is therefore an unproven capacity assumption, not an observed viable architecture. If pasture must replace two SW wheat tiles, recalculate all wheat rotations; if additional hires are needed, subtract their actual Fibonacci cost.

**Failure conditions:** no meaningful feed purchases are displaced at the required times; bulk grain fills shed and displaces high-value output; additional cows saturate milk demand; no free nearby pasture exists; grain harvest/animal service peaks compete; or the required late labor costs exceed the incremental herd contribution. Compare cows, sheep and neither under the same dated market scenarios; species preference is not fixed by gross product prices.

## Compare acquisition policies across all three architectures

| Policy | What it buys | Structural limitation |
|---|---|---|
| A: cash threshold | Land when cash exceeds a chosen amount | Does not reserve workers, feed delivery, seeds or sales capacity; reproduces stranded land/core displacement risk. Useful as a diagnostic ablation only. |
| B: immediate feasibility | Land when cash, current staff, seed and workload gates pass | Safer, but an existing overcommitted farm may never present slack. A current-turn gate misses a harvest peak and cannot intentionally prepare for SW. |
| C: forward commitment | A dated entire-farm production plan; land is one dependent purchase | Coordinates earlier hires, capital, selective admissions, crop cohorts and sales. Must allow cancellation/downsizing when its resource certificate fails, rather than forcing unsafe purchase. |

Use forward commitment in the recommended prototype. Economic plans must value the *with versus without* whole-farm trajectories, including changed own supply and preserved/removed core activities. Full-season staffing and feed obligations belong to that comparison; already-paid costs are sunk only in later continuation decisions.

## Can any of these establish a $130,000 average?

No. Against the separate P6 context mean of $101,035.79, the arithmetic gap is **$28,964.21**. Against the P6.1 control it is $30,109.22; against P4.2 it is $27,013.81. These are contextual target gaps, not interchangeable matched results.

Even A's strong stock case adds only $14,529, B $11,523, and C+ $25,961 **before their unproven service/capital assumptions are charged**. C+'s strong result still falls about $3,003 short of the P6 context target, and is not a probability-weighted expectation. A's baseline-price gross calculation around $32k net before core/market effects is invalid as a target forecast: the whole-farm price/capacity debit is material.

At a net contribution of $100 per additional monetized unit, closing $28,964 needs about 290 additional units; at $200 it needs 145. The actual requirement is product-specific and must be solved along the nonlinear price curves, after seed/feed/wage/core costs. Two ideal D10 cows add 42 milk, not hundreds of units. Storage/care/route opportunities cannot simply be stacked on these figures: routing is already required to make A/C fit, care is assumed in their animal output, and market re-pricing already accounts for changed sales.

The defensible outcome of this audit is a set of falsifiable architectures and a route to test them, **not a claim that the $130k target is already economically demonstrated**.
