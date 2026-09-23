# SW architecture: current state and historical failure audit

Audit date: 2026-09-23. Verified repository and remote branch HEAD: `975da5e1683f1bb57463cb9478344d0acf379d58`, branch `experiment/sw-p13-planting-gate`. No later remote commits were found. This report changes no production policy. Protected seeds 98001–98050 were not executed or used as discovery data.

## Evidence standard and baseline lineage

The graph was consulted at Tier 2, project `D-website-project-kaggri-ox`, generation `2026-09-19T14:29:44Z`. Coverage metadata is stale/not-tracked for newer experiments and excludes `replays/`. Historical scripts, JSON artifacts, reports, and relevant current source were therefore read directly. Graph absence is not evidence that a file or behavior is absent. Original historical reports remain intact; corrections below supersede their interpretations for this design.

The production lineage is promoted P2.3, `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e`; repository HEAD contains later disabled experiments and diagnostics. `P51_T1_TWO_CYCLE_CARROT_ENABLED=False`, `P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED=False`, and `P41_SW_ZONAL_EXPANSION_ENABLED=False` remain production defaults. Actual packaging/runtime parity is documented in the recommendation and baseline diagnostic artifacts. A branch name containing SW is not proof that production develops SW.

Independent panels must remain separate:

| Evaluation | Panel and baseline | Observed mean final cash | Interpretation |
|---|---|---:|---|
| P2.3 promotion | 100 matched cases, seeds 89001–89050 | old $101,467.43; promoted $101,918.93 | +$451.50 paired, CI [$213.63,$689.37] |
| P4.1 control | 20 cases, 97001–97010, rotating five opponents, both seats | $100,366.65 | matched control for forced late SW only |
| P4.2 | 100 games, 96101–96110 × five opponents × two seats | $102,986.19 | separate market audit panel |
| P6 baseline | 100 games, 96401–96410 × five opponents × two seats | $101,035.79 | separate baseline diagnostic panel |
| P6.1 control | 100 games, 96411–96420 × five opponents × two seats | $99,890.78 | separate storage experiment control |

These are not a rising or falling score trajectory. Opponent, seed, source snapshot, horizon, and telemetry definitions must accompany each number.

## P4.1: what the original experiment actually establishes

Sources: `simulations/experiments/run_p41_feasibility_test.py`, `simulations/experiments/results/p41_feasibility_test.json`; reproducible independent reaggregation in `simulations/experiments/sw_leader_audit.py` and `simulations/experiments/results/sw_leader_audit/p41_recomputed.json`.

Treatment acquired SW on day 14 in 20/20 games, kept an eight-tile zone, and assigned hands 11 and 12 to its agriculture. Hybrid intent was four strawberry coordinates and four wheat coordinates, with later wheat/carrot fallback. No additional workers were purchased specifically for the new zone. Control was archived `agent/` at P2.3; treatment was a worktree snapshot. The saved manifest does not hash that treatment snapshot, so the exact treatment bytes cannot be reconstructed solely from the result JSON.

| Measurement | Control | Treatment | Meaning |
|---|---:|---:|---|
| Final cash, mean/game | $100,366.65 | $95,547.55 | engine final-money field |
| Paired difference | | −$4,819.10 | 95% t CI [−$11,531.97,+$1,893.77]; small noisy feasibility screen |
| Core watering compliance | 84.2525% | 79.8030% | pre-hour-23 action snapshots; −4.4495 percentage points |
| `core_plant_deaths` counter/game | 263.55 | 284.90 | **not a death counter**, see below |
| `missed_feedings` counter/game | 16.55 | 17.50 | pre-hour-23 unfed observations; not starvation/death transitions |
| Hands 11+12 core agricultural action attempts/game | 141.00 | 29.40 | −111.60 core operations from the reassigned pair |
| All-unit core agricultural action attempts/game | 1,327.30 | 1,227.20 | −100.10; other workers recover only +11.50 |
| SW agriculture by hands 11+12, panel total | 0 | 2,598 | 129.90/game |
| SW agriculture by other units, panel total | 0 | 1 | isolation not perfectly satisfied |
| SW strawberry yield attached to harvest attempts | 0 | 241 panel / 12.05 game | not settlement revenue |
| SW wheat yield attached to harvest attempts | 0 | 853 panel / 42.65 game | not settlement revenue |
| SW carrot yield attached to harvest attempts | 0 | 22 panel / 1.10 game | omitted from original short summary |
| Negative cash observations | 0 | 0 | financial safety observed at sampled steps |

### Corrections required before using the result

1. **The crop production figures 241 strawberries and 853 wheat are totals across twenty treatment games.** Reading them as per-game output exaggerates regional production twentyfold.
2. The harness increments `core_plant_deaths` for every live PLANT at hour 23 with `consecutive_unwatered >= 1`. It neither observes the daily refresh nor checks PLANT→WEED transitions. The +21.35 is an increase in repeated stress observations, **not 21.35 proven crop deaths**. Lifecycle expiry, intentionally unwatered wheat, and actual dehydration require separate accounting.
3. The watering snapshot occurs before that hour's issued action. It includes all crop types and therefore does not establish bonus-water compliance for the economically relevant subset. The 98% feasibility target was already missed by the control.
4. `total_starvations=350` means the treatment's twenty-game total of pre-action unfed flags. It is neither zero nor a confirmed count of starvation events. The baseline equivalent is 331. Do not repeat the claim that the run proved zero starvation.
5. Harvest telemetry reads the crop and `yield_units` before issuing HARVEST; it does not validate maturity, actual success, inventory receipt, delivery, sale, unit prices, seed expense, or regional provenance. The metric is a yield-weighted attempt proxy.
6. The script has **no regional sales or transaction-cost hooks**. Accordingly, “+$1,950 direct SW profit” and “−$6,769 core revenue” are **not a reconciled cash waterfall**. Their difference equals the observed loss arithmetically, but neither component is established by this experiment. There is no exact evidence to allocate the $4,819 among core crops, livestock, price changes, seeds, feed, and routing.

### Root cause versus symptom

The directly verified architectural intervention is **exclusive capacity transfer without a replacement capacity or workload-removal plan**. In current `agent/execution/task_scheduler.py::assign_tasks` (P4.1 eligibility block), ordinary NW/NE WATER, PLANT, DIG, FERTILIZE, and HARVEST tasks exclude units 11 and 12 when SW is unlocked. Urgent survival/decay exceptions remain. SW agricultural tasks are restricted to those units. `get_home_quadrant` assigns them SW home ownership; the remaining units are repartitioned across the core. This is deliberate reservation of two already productive workers, not the discovery of two idle workers.

`agent/strategy/macro_planner.py`'s P4.1 controller adds work on eight coordinates and removes SW from the generic empty-tile loop, but does not retire an equivalent lower-value NW/NE portfolio. Thus core ordinary work loses eligibility while its production obligations remain. The measured −111.60 core agricultural attempts from these workers and lower watering compliance corroborate the displacement mechanism. Their remaining 29.4 core attempts include pre-purchase activity and exceptions; they are not spare capacity estimates.

The downstream symptoms are fewer core services, more stressed plant observations, and lower final cash. Actual dehydration deaths, missed repeat harvest counts, and their exact dollar contribution remain **unresolved**, rather than proven by the old report. Excess travel, late hires, feed labor, and crop mix are plausible amplifiers; this harness does not separately quantify them. A definitive attribution requires replaying the matched discovery scenarios with immutable treatment source, successful-action hooks, hourly queues and eligibility, crop lifecycle transitions, and exact settlement accounting.

Farm-wide agricultural attempts actually rise by **29.85/game** (SW +129.95 minus core 100.10). Thus even a total action-count improvement does not establish profit: the regional value, successful completion and deadline of the displaced actions matter. The standard saved evaluation horizon also ends before the last nominal 24-hour cell; never assume 720 executed action turns merely because the loop or episode configuration says 720.

The defensible answer is therefore: **P4.1 lost $4,819.10/game while transferring two productive core workers to new SW obligations. It proves that this transfer did not preserve core service or final cash; it does not prove the published $1,950/−$6,769 decomposition or the claimed additional deaths.**

## Earlier SW failures and what their controlled contrasts establish

| Experiment / source | Matched result | Architectural lesson and limitations |
|---|---|---|
| Early fixed-hiring design, `docs/experiment fixed hiring implementation_plan.md` | design proposes 4→8→10→12 hands; NE D6, SW D9 | design intent, not measured proof. Old animal/feed/crop constants cannot be imported into current economics |
| `sw_progressive_experiment_results.json` | 50 cases: liquidity/discrete SW −$6,387.52 vs own control; Dusta-prior progressive −$5,383.58 | progressive activation did not make expansion pay; these are older random/starter opponents, not the modern five-opponent panel |
| `definitive_sw_tournament_results.json` | 50 cases: primary progressive −$15,628.88; discrete −$16,200.46; prior progressive −$16,578.22 vs frozen control | SW bought in early window but additional activity displaced valuable livestock/core output; accounting fields such as zero hire cost indicate incomplete category instrumentation |
| P1 committed-herd purchase gate, `sw_p1_findings.md` | 20 cases: −$20,185.80; 15/20 SW purchases; no-purchase cases tied | changing the purchase model alone triggers damaging downstream architecture |
| P1.1 scheduler, `sw_p1_responsive_scheduler_results.md` | 40 cases: +$11,053.85 vs P1, still −$8,790.55 vs control | **strong causal evidence** rigid home-zone partition caused a large share of loss; responsiveness alone insufficient |
| P1.2 serviceability activation, `sw_p1_serviceability_activation_results.md` | 40 cases: −$9,653.90 vs control; −$863.35 vs P1.1 (CI crosses zero) | protecting only one activation path and using optimistic capacity assumptions does not constrain actual whole-farm demand |
| P1.3-A generic planting gate, `sw_p13_planting_gate_findings.md` | 40 cases: +$1,979.95 vs P1.2; still −$7,673.95 vs control | closing SW pasture planting bypass causally helps, but is not an architecture |
| P1.3 factorial, `sw_p13_factorial_findings.md` | livestock cap +$6,256.27 vs A; tight-soil +$539.75 with CI crossing zero | herd commitments and core workload interact materially. Control mean differs from the earlier screen; never splice their score columns |
| P1.3-C validation, `sw_p13_heldout_validation.md` | 200 cases, older 81001+ panel: −$3,805.92, 94 SW purchases, 138 losses | apparent discovery recovery did not generalize. This historical panel is distinct from protected 98001–98050 |
| Two-quadrant livestock-cap salvage, `livestock_cap_2q_salvage.json` | 100 cases: −$317.43, CI [−$1,588.36,+$953.50] | generic smaller-herd restriction alone not validated as profitable; reduced feed/stress is not synonymous with higher cash |
| P2.3 wheat allocation promotion, `p23_promotion_validation.json` | +$451.50 on its independent promotion panel | safe opportunity exists at specific margins, but tiny relative to target |
| P3.1 harvest priority, `p31_harvest_priority_ab.json` | +$674.20, CI [−$390.83,+$1,739.23] | score uncertainty remains; promoting urgency alone not established |
| P3.2 care priority, `p32_care_priority_ab.json` | −$3,454.85 in 20 cases | additional care can displace more valuable work; gross animal bonus is not net return |
| P4.1 late isolated SW | −$4,819.10 in 20 cases | even two-worker transfer harms core service; metrics corrected above |
| P5.1 two-cycle carrot / P5.1-C | −$1,020.68 on 100 paired cases | replacing local wheat increased purchased feed and disrupted feeding timing despite successful crop execution; feed location/time matters |
| P6.1 and P6.1-C-R | +$1,439.86 mean, only 2.8% fewer discards | storage mechanism failed; heavy outlier dependence and opponent losses; remains disabled |

Supporting history also includes `pre_ne_capital_experiment_results.json`, `land_affordability_ab_results.json`, `round2_sw_crop_frontier_results.json`, `round3_strategic_sw_results.json`, `sw_serviceability_results.json`, the Stage 8B reports, and archived SW-timing packages. These establish the existence of many prior coupled experiments, not matched estimates against current production. Their old score levels, request-based costs, incomplete telemetry and runtime differences preclude pooling them into one effect estimate. For a new experiment, archive exact runtime/config/engine hashes and rerun the unchanged current baseline on the same scenarios.

## Historical claims that must not drive this redesign

- `sw_p1_post_purchase_diagnosis.md` correctly identifies rigid partitioning, subsequently supported by P1.1's controlled contrast. Its $3,000 SW-only price is wrong: that is cumulative NE+SW land expense, not the $2,000 marginal SW price. Its harvest-attempt dollar multiplication is a model, not settlement accounting.
- The P1 and P1.2 diagnostic narratives disagree about which animals miss feed and whether the issue is transit or resale. Preserve case-specific findings; do not assert one universal feed root cause across different runtimes. The later controlled P5.1-C establishes an additional feed timing mechanism.
- `docs/sw_strategy/sw_quadrant_fix_design.md` and its duplicate propose a $26k–$30k SW profit engine with nine extra animals and fifteen wheat tiles. They are **unvalidated designs**, with obsolete feed simplifications and optimistic throughput. Saved leaders actually use mixed SW crops and variable animal counts; see the leader report.
- `docs/p6_worker_transit_audit.md` describes mandatory shed trips for seed carrying and water refills. Seeds are global and watering has no refill resource; that mechanism is false. A measured move share can still be useful, but arbitrary “avoidable” fractions and recoverable cash are not observed gains.
- `docs/p6_time_congestion_analysis.md`'s narrative (1–4 early workers, NE D7–8, manual midnight returns) is not reliable current-policy ground truth. Automatic midnight handling and hired-hand reset must be taken from the engine. Feed-empty snapshots do not alone prove failed feeding. The new baseline diagnostic separates these.
- P4.2's “zero overflow/100% realization” generalization is superseded by P6's instrumented midnight-discard evidence. End-of-season empty inventories do not imply that all earlier output was sold.
- P6's proposed recovery sums are untested opportunity estimates, and P6.1 subsequently failed its discard mechanism. They must not be added to SW modeled gains to manufacture $130k.

## Constraint diagnosis and design implications

The strongest historical evidence identifies **a mismatch between economic commitments and executable service capacity**, not a universal shortage of nominal worker count. Purchase logic, crop activation, animal investment, feed reserve rules, and dispatch have separate representations of available resources. They can each appear feasible while their combined hourly obligations are not. Static zones strand usable capacity; unconstrained sharing can destroy feed deadlines; aggregate AP models miss travel and simultaneous harvest/maintenance peaks.

The redesign must commit an entire production plan several days ahead, reserve time-indexed feed and treasury, and admit new crop/animal obligations only against an executable regional service plan. Deliberate substitution is necessary when new profitable activity outranks existing tasks: reduce a measured lower-return obligation before acquiring its replacement. This does not imply retiring healthy mature repeats or starving animals. See the labor model, economic model, architecture alternatives and validation plan for candidate-specific budgets and falsification gates.

No historical controlled result proves a $27k–$30k average improvement. SW is a strategic requirement for the next architecture, but its profitability and path to $130k remain hypotheses to test.
