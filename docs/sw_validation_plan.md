# SW architecture validation plan

Date: 2026-09-23. Research baseline: `975da5e1683f1bb57463cb9478344d0acf379d58`, branch `experiment/sw-p13-planting-gate`.

This is a proposed program, not authorization to implement or promote a strategy in this audit. No new architecture was implemented. The primary outcome is **paired incremental final cash**, with feed, execution, and treasury safety as hard constraints. SW utilization is a mechanism check, not the objective function.

## 0. Establish a reproducible baseline and correct measurements

1. Freeze source commit, engine file hash, Python/package versions, submission file hashes, imported module paths, configuration values *after initialization*, opponent implementations, seed, seat, and episode length in every run manifest. Do not call a harness-configured ArmA control and an unconfigured `submission/main.py` import the same runtime without checking equivalence. `config.py` initially sets `QUADRANT_HARD_BLOCK={4}`, whereas `set_sw_experiment_arm("ArmA")` sets `{3,4}`. Tests with an ArmA fixture do not prove import defaults.
2. Retain `P51_T1_TWO_CYCLE_CARROT_ENABLED=False`, `P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED=False`, and the other baseline settings in the control. Reject mixed imports from `agent/` and `submission/`. Use a fresh process per arm/scenario or prove complete reset of module state, experiment switches, missions, forecasts, and feed holds.
3. Record state before unit actions, after unit actions, after market, before EOD, and after EOD. Engine units act before market; purchases cannot fund the same turn's unit action. EOD after the final market opportunity cannot be monetized. Hires expire daily and do not act in their purchase turn.
4. Intercept the engine functions that actually execute. If wrapping a scheduler, patch the alias imported by `main`, not only its original module. Assert hourly counters populate the true hour, and sum hourly counters to independently observed daily totals. The original P6 action congestion map failed this requirement.
5. Run engine-exact crop calendars, wage curve, inventory-price slippage, and animal production self-checks. Verify four production ticks for tomato/strawberry, three-day fertilizer duration, mortality/decay, and the last market opportunity. Include the planting-day WATER action and actual access coordinates. Do not invent seed carrying or water refills.
6. Compare instrumented and uninstrumented actions/rewards on identical existing discovery scenarios. Require identical actions, transactions and final cash; hashes/identity alone cannot prove behavior invariance.

### Required accounting artifacts

Store per-scenario event rows and daily/hourly aggregates, with units and definitions:

| Ledger | Required fields and closure |
|---|---|
| Cash | Opening cash + actual sales - seed/feed/animal/hire/land/other purchases = closing cash. Every day closes to engine precision; adjacent day boundaries agree. |
| Wheat | Opening shed+carried + harvested+actually bought - actually fed-sold-discarded = closing shed+carried. Keep harvest after last playable hour separate. Purchased wheat is not synonymous with feed consumed. |
| Other products | Production, harvest, tile decay, carrier/shed transfer, sales, discard, closing tile/carrier/shed inventory. Fertilizer usage is a sink, not an unsold backlog. |
| Workers | Actual available worker-hours after hire settlement; successful work, movement, PASS, unchanged/failed attempts. Classify task location and worker location separately. |
| Regional crop state | Crop identity and cohort, planting/harvest events, active tile-hours, mature waiting hours, successful watering, mortality transitions and causes. Exclude shed access from agricultural utilization denominator. |
| Animals | Placement, species/position, feed and CARE success, production, collected fertilizer, escape; distinguish a pre-H23 unfed flag from an EOD missed feed or escape. |
| Market | Actual unit price and inventory before/after each transaction; candidate rejection is not an engine-dropped order or a lost sale. |
| Planning | Committed production calendar, reserved cash/feed, regional service deadlines, rejected commitments and reason, predicted versus realized routes/output/prices. |

Cash cannot be assigned exactly to quadrants merely by multiplying regional harvested units by farm-average prices: goods mix in carriers/shed, are fed, discarded, or sold at different prices. Track tagged inventory lots if regional realized sales are a required mechanism metric; document a deterministic FIFO convention and report it as attributed revenue. Whole-farm transaction cash remains exact. Price effects must include incumbent output, not just new SW units.

## 1. Minimal architectural prototype, on a subsequent experimental branch

Select one complete architecture from [alternatives](sw_architecture_alternatives.md). Implement a single coherent commitment path: target purchase window, crop cohorts, daily hire plan, optional herd admissions, feed/cash holds, and deadline-based regional execution. Keep it behind one default-off experiment selector. Supporting changes needed to execute that architecture are part of its treatment; do not silently add P51, P61, unrelated trading changes or another crop experiment.

First use a small SW tranche with the same accounting and scheduling semantics as the intended full portfolio. This is an execution test, not proof that the small tranche's economics scale linearly. On rejections, log whether capital, feed delivery, hourly service, or market margin failed. No land purchase should be counted as successful activation.

Unit checks should target engine contracts and conservation, not reproduce the implementation. Required cases: simultaneous planting/watering and feeding deadline, second hire batch, feed arriving after unit actions, crop harvest conflicting with animal output, same-turn deposit then sale, repeated crop yield cap, final-day delivery, and cancelled expansion releasing only discretionary holds.

## 2. Execution feasibility on reused discovery seeds

Reuse already exposed diagnostic scenarios. Do not spend fresh evaluation seeds while fixing obvious execution failures. Compare control and treatment with identical seed/opponent/seat, including a high-output opponent. Use a minimum of 10 games before interpreting a mechanism.

The numerical operational thresholds below are **prospective design gates**, not observed achievements. Freeze them before the discovery tournament. Adjust only on the reused mechanism panel, with a recorded reason.

| Metric | Proposed gate |
|---|---|
| SW commitment/purchase | Target D6-D8 for the early crop architecture; buy only after its cash, feed, seed and hourly capacity certificate passes. Report purchase probability and all non-purchases. |
| Planting ramp | At least 8 crop tiles by purchase+1 day, 16 by +2, and the chosen target up to 24 by +3; count successful PLANT, not queue entries. If the modeled crop deadline is earlier, enforce the earlier limit. |
| Productive utilization | At least 80% of planned crop tile-hours over the admitted cohort's lifecycle; exclude reserved center access and do not count empty pasture as crop utilization. |
| SW harvest | At least 90% of the admitted engine-calendar harvest units, with terminal/post-game units excluded; publish by crop and cohort. |
| SW realization | At least 90% of harvested sale-intended units monetized before scoring, or explicitly accounted as on-farm feed substitution. No double counting of wheat sale and saved feed purchase. |
| Core retention, core-preserving arm | NW+NE realized output/reference-valued mix at least 98% of matched control; no more than 1 percentage-point decrease in growth-relevant watering compliance. |
| Core retention, substitution arm | Explicitly preregister each removed crop/animal cohort; retain at least 98% of *preserved* cohort output. Debit foregone contribution of removed cohorts in cash waterfall. Aggregate core output can fall intentionally. |
| Crop safety | Zero additional avoidable crop mortality among preserved crops; track lost bonus watering and missed production ticks separately from death. |
| Animal safety | Zero new missed required feeds due to the treatment, zero escapes, zero feed-commitment insolvency. Never omit feeding an already purchased animal to make the labor budget balance. Separate terminal no-payoff feeding convention from earlier obligations. |
| Treasury | Nonnegative actual cash; required feed/hire commitments funded at each deadline. No false positive capital certificate when market receipts are unavailable. |
| Worker efficiency | At least 95% of assigned deadline-critical operations succeed before deadline; projected regional busy-hour demand does not exceed available actions after actual travel. Report route and productive shares, not just utilization. |
| Storage | No increase in reference-valued discarded high-value goods versus control; feed headroom and deposit deadlines feasible under sequential unit/market ordering. |
| Runtime | No strategy fallback, illegal-order increase, timeout or nondeterministic import-dependent allocation. Measure high-percentile runtime against the competition's pinned limits. |

Failure is not repaired by simply suppressing the counter: stop admitting new SW workload, diagnose the earliest broken dependency, then rerun the same mechanism panel. Maintain feeding and survival of commitments already made.

## 3. Matched discovery tournament on genuinely fresh seeds

Maintain a registry with seed, role, first-use date, experiment, opponent/seat coverage, and source manifest. Search all experiment manifests/results before selecting a new block; a seed absent from one report is not necessarily fresh. The audit does **not** nominate an unverified block as untouched.

- Reserve and assert exclusion of **98001-98050** in every discovery/audit script.
- Initial discovery: at least 10 fresh seeds x 5 diverse opponents x 2 seats = 100 matched pairs, 200 games per candidate/control comparison.
- Pair on seed, opponent, and seat. Save all failures and exceptions, do not silently drop bad games. Do not mix older panel controls into the comparison.
- Randomize/interleave arm execution order; pin engine and opponent versions. Use the same external randomness per scenario. A deterministic policy may still face path-dependent opponent behavior; record both agents' trajectories.
- Report mean/median paired delta, standard deviation, minimum, 10th percentile, win fraction, both seats, each opponent, leave-one-seed-out sensitivity, and concentration in the top 1/5/10 cases.
- Use seed-cluster bootstrap confidence intervals: the ten opponent-seat cases sharing a seed are not ten independent seed observations. State uncertainty due to only ten seed clusters; extend to a preregistered larger panel if inconclusive. Do not repeatedly peek and stop at a favorable p-value.
- Preregister one primary candidate. If comparing several architectures, correct for selection/multiplicity or use a separate fresh confirmation panel after selecting the winner.

### Economic decisions

**Advance:** positive mean paired cash with a 95% seed-cluster interval above zero, at least +$2,000 mean as a minimum useful architectural improvement, operational gates passed, and no unexplained severe opponent/seat loss. This is a first-stage improvement gate, **not** the $130k success criterion.

**Iterate:** reliable SW production but uncertain/negative net cash, or cash improvement with a failed proposed mechanism. Reconcile the entire delta before changing a policy. Treat a +$1k incidental market change as incidental, not validation of a land-development thesis.

**Reject:** persistent core damage exceeding SW net margin, negative conservative whole-farm contribution, feed/execution failures, or dependence on a market regime/opponent absent from deployment expectations.

**Target attainment:** evaluate the finalized architecture's mean final cash against $130,000 on the preregistered relevant opponent/seat distribution, alongside paired improvement. Report its uncertainty interval. A target mean on one reused seed is not evidence of $130k average performance.

## 4. Controlled causal iteration

For the selected coherent prototype, run ablations: purchase without activation; same SW production with fixed versus deadline-aware regional allocation; old versus early hire timing; baseline versus explicitly reduced herd admissions; normal versus committed portfolio-aware selling. Never intentionally starve livestock for an ablation. These diagnostic ablations explain a failed architecture and are not individually promotable benefits to add together.

Reconcile `delta cash = delta actual sales - delta actual spending` first. Then quantity/price/interactions, wheat consumption versus churn, lost core output, inventory destruction, delayed cash receipts and added wages. Close the labor ledger by hour. Distinguish fewer emitted WATER actions due to fewer crops from a service-efficiency gain.

Retest new choices on reused diagnostics; one frozen selected version proceeds to a new fresh confirmation block. Track all iterations in `docs/knowledge/experiments.md` without rewriting earlier results.

## 5. Protected validation, only after design freeze

Seeds **98001-98050** remain unopened and unused throughout this audit and discovery. Use them only after the architecture, settings, target opponent mixture, gates, and statistical protocol are finalized and discovery/safety gates pass. Hash the final candidate and control before first use. Run all prespecified cases including both seats; publish the entire result, including failures.

No tuning on held-out outcomes. If held-out evidence invalidates the choice, mark the version failed and the panel spent. A new development cycle requires a newly protected panel. Official submission changes and promotion belong to the later implementation task, after validation—not to this research task.

## Invalidation and stop conditions

The recommendation is invalidated if: its price curves under added own/opponent supply leave insufficient contribution after core displacement; an executable hourly calendar needs more labor than the allowed cost envelope; early land funding delays productive NW/NE cohorts more than it earns; reduced herd admissions remove more net cash than crop substitution supplies; extra deliveries destroy essential watering/feed service; or realistic opponents consistently depress its chosen products. In any of these cases, select a different complete architecture rather than loosen a land threshold.
