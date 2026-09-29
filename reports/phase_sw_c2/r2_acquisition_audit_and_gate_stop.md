# SW-C2-R2 acquisition audit and correctness gate stop

Date: 2026-09-29. Status: **STOPPED at the baseline correctness gate; R2 is not implemented or validated.**

## Repository and protected assets

Local HEAD and fetched `origin/experiment/sw-c2-workforce-coordinator` both equal `4dfbd9b217264f465a66c95f38ad3145a45d4f6b`. There are no subsequent commits to inspect. The initial working tree was clean. Audit work uses dedicated branch `experiment/sw-c2-r2-early-acquisition`.

Canonical commit `faa6cb99f66b2066e639806d0eabc72a0c7d7982` exists and was not modified. `dist/submission.zip` SHA-256 is `E7FF7C5A4B91364C10898CB8A22E4680C9330F1E30171593DA2D1EED7DD4ED41`. Installed Kaggriculture engine SHA-256 is `BC8A54879EF02C7EA64B8B333D6A976F0EA65C4949149D01F463F23BCCEE653E`, matching the pinned manifest.

Graph project `D-website-project-kaggri-ox` was checked before discovery. Generation `2026-09-23T14:30:22Z` is stale: acquisition files report changed metadata and newer workforce/reservation files report untracked metadata. Findings below use direct source fallback and independent read-only acquisition and correctness audits. Line references refer to the starting commit. The skill's `define_subagent` tool is unavailable; independent reviews used the available collaboration agents.

## Acquisition pathway

| Stage | Source | Current behavior |
|---|---|---|
| Macro baseline request | `agent/strategy/macro_planner.py:1849` | Passes committed seed cost as 0.0 to the expansion path. |
| Baseline timing | `agent/config.py:509`; `agent/strategy/expansion_planner.py:259`, `:545` | SW timing defaults to D9. Configured $2,204 is a legacy diagnostic threshold; actual purchase uses the dynamic protected-resource total below (`expansion_planner.py:909`). Early-liquidity/pure-economic variants use D7; an optional delayed day can increase the timing threshold. This is a policy restriction, not an engine unlock rule. |
| Baseline protection | `agent/strategy/expansion_planner.py:584`, `:773` | Reserves hires, actual feed, missing seeds and cash; early-liquidity mode protects hiring shortfall, actual feed, committed seeds and $300. |
| Whole-farm readiness | `agent/strategy/whole_farm_planner.py:952` | PREPARING starts at D4; $2,200 can move the planner to READY. |
| Whole-farm approval | `agent/strategy/whole_farm_planner.py:1314` | Requires cash, feed safety, positive estimated portfolio delta, labor and lifecycle certificates. No explicit D8–D10 preference or buy-tomorrow alternative. |
| Controller approval | `agent/strategy/sw_tranche_controller.py:329`, `:356`, `:398` | Checks portfolio economics/certificates initially, then caches approval. |
| Treatment override | `agent/strategy/macro_planner.py:1853` | Replaces baseline rejection with controller approval, including a `before_day_9` rejection. Cached approval can be retried without fresh admission. |
| Market construction | `agent/market/order_builder.py:46`, `:1165`, `:1220` | Priority is hires, protected feed, land, optional feed, seeds, animals. Records `land_slots` if land is omitted; approval alone does not prove emission. |
| Final action | `agent/main.py:1203` | Shared central arbitration/fallback truncation still controls the final ten market orders. Retained final orders must be inspected. |
| Settlement | Installed `kaggriculture.py:712` | `_do_buy_land` checks the next quadrant and available funds; no day restriction. Order is NE, SW, SE, priced $1,000, $2,000, $4,000 (`:96`). |
| Activation | `agent/strategy/macro_planner.py:2140`, `:2233` | Waits for observed SW unlock. Existing seeds permit PLANT tasks; missing seeds create BUY_SEED orders without same-turn planting tasks. |

Other timing controls include the general D20 land cutoff (`agent/config.py:427`), optional P41 defaults D14/$15,000/0.90 core occupancy (`:1101`), and strategic fallback D9–14 (`expansion_planner.py:872`). These conditional policies must not be confused with engine legality.

**D4 versus D9:** a D4 purchase is mechanically legal after NE. The whole-farm D4 readiness path plus treatment override explains how it can occur despite the baseline D9 setting. This establishes the source pathway, not the timestamp of a particular historical settlement.

OrderBuilder retains current hiring/feed protection, but that does not refresh a cached labor certificate or future crop obligations. Seeds and labor are not established as ready merely because admission approved land. Worker actions precede market settlement, so newly bought land/seeds and hired workers cannot service an earlier unit action in the same turn (pinned manifest and interpreter ordering).

## What the historical timing evidence establishes

Keep the following events separate:

1. Recommendation/approval: controller `:398`.
2. Emitted order and retained slot: controller `:712`.
3. Successful settlement: engine cash-changing BUY_LAND hook.
4. First observation of SW unlock: controller `:767` (normally the following observation, not the settlement action timestamp).
5. First physical planting: controller `:803`.
6. Successful harvest, inventory delivery and realized sale: require separate engine outcomes and attribution.

Controller `confirm_purchase` (`:698`) and unlock observation (`:790`) hardcode a $2,000 deduction instead of independently reconciling it. Live `record_turn` (`:976`) treats submitted SELL/HARVEST/FEED actions as executed; estimated SW revenue uses a fixed 16-unit cap. Conservation reconciliation (`:847`) assigns unexplained positive inventory differences to discarded overflow. These are not sufficient independent proofs of economic fulfillment.

The existing P5 artifact `simulations/results/phase_sw_c2/sw_c2_matches_p5_discovery_confirmation.json` supports **8/12 successful SW acquisitions in each of B and F**. Purchased cells have two land purchases totaling $3,000; non-purchased cells have one totaling $1,000. The runner records successful engine cash-changing land calls (`scripts/run_phase_sw_c2_experiment.py:619`) and computes SW acquisition from purchase count greater than one (`:932`). Equal purchase rates conceal different cells:

| Arm | No-SW cells |
|---|---|
| Frozen B3C B | 97013 / pure_wheat_rush / seats 0 and 1; 97014 / pass / seats 0 and 1 |
| C2 F | 97014 / pass / seats 0 and 1; 97014 / cow_milk_engine / seats 0 and 1 |

**The precise causes of these non-purchases remain unresolved.** `record_land` (`:257`) collects transaction step/day/hour, but returned results (`:873`) omit those transactions and rejection lifecycle records. Saved P5 artifacts cannot establish exact settlement, first planting/revenue timestamps, or which resource caused each rejection. Do not infer those causes from the aggregate 66.7% rate. Fresh instrumented replay is required after correctness gates pass.

## Independent workforce/reservation findings

| Severity | Source | Confirmed defect |
|---|---|---|
| High | `agent/execution/workforce_capacity_forecast.py:147`, `:193` | Carried wheat is accepted for FEED but not decremented; one carried unit can support multiple projected feeds. |
| High | Same file `:130` | `release_step` is ignored in scheduling; missing/later prerequisites default to the current step. |
| High | Same file `:221`, `:303` | Future hands use H06/18-hour assumptions, inconsistent with pinned H0 market hire followed by H1 availability. Funding and future hire execution are not proven by today's observed hand count. |
| High | `agent/strategy/crop_cycle_reservation_manager.py:345`; forecaster `:299` | Admission uses mock hands, house position and midnight; aggregate hours plus fixed transit ignore observed positions, inventories, deadlines and prerequisite execution. |
| High | Reservation manager `:453` | Commit does not register reservation obligations into the shared ledger. Subsequent normal admission can miss earlier commitments. |
| High | Reservation manager `:478` | No live reconciliation caller was found in the bounded `agent/**/*.py` source search; the existing call is a test. Empty/unplanted tiles can count as fulfillment; fallback accepts half the harvest obligations. No verified inventory or sale evidence is required. |
| High | Reservation manager `:391` | Fixed 0.12 displaced wheat per worker-hour and an invented wheat-price expression determine the asserted whole-farm delta, without calibration evidence. |
| Medium | Reservation manager `:229`, `:287`, `:445`, `:530` | Trials mutate counters, telemetry and rejection logs despite the strictly side-effect-free requirement. |

PLANT resource modeling also assumes carried/shed seed items (`forecaster:156`; reservation manager `:302`). Engine seed semantics must be explicitly verified and tested before replacing this path; this audit does not claim that correction has been implemented.

The initial tranche and acreage ladder are already separate decisions. `sw_tranche_controller.py:467` requires confirmed ownership, a later day, day-start and room below the cap before incremental admission. The cap defaults to 24 (`agent/config.py:1755`). However, controller `:507` substitutes the maximum of observed and scheduled workforce. The 8→12→16→20→24 option must survive R2, using executable evidence rather than this optimistic substitution.

## Gate disposition and remaining deliverables

The user required stopping at any failed correctness or safety gate. Baseline regression produced failures before implementation. No behavior code or default flags were changed, and no R2 games, seed selection, timing experiments, P3 contrasts, P6 optimization or promotion were started. Protected seeds 98001–98050 were not selected or run by this work. Seed provenance selection remains deferred; this is not a claim that a fresh discovery panel has been cleared.

R2 is **not ready for formal discovery or independent confirmation**. The D8–D10 adaptive policy, corrected resource integration, settlement/utilization traces and paired economic results remain outstanding. Higher purchase rate alone cannot satisfy acceptance. Resume by resolving the failed baseline gate, then correcting executable resource accounting and observability before validating early acquisition. Do not use existing heuristic deltas as verified counterfactual final cash.

## Baseline regression result

Command, run before any behavior edits using installed Python 3.12:

```powershell
rtk proxy 'C:/Users/rohit/AppData/Local/Programs/Python/Python312/python.exe' -m pytest agent/tests -q --basetemp=scratch/sw_c2_r2_pytest
```

Result: **6 failed, 1463 passed in 671.67 seconds (11:11)**. This is the complete `agent/tests` suite, not a claim that every simulation test elsewhere was run. No additional experiments were started after the failed gate.

| Failed test | Observed assertion |
|---|---|
| `test_animal_service_economics.py::test_19_agent_and_submission_sync` | `agent/config.py` differs from `submission/config.py`. |
| `test_feed_feasibility.py::test_phase_b_repair_ledger_fail_closed_in_herd_plan_and_live` | At line 1482, simulated herd-planner failure yields `feed_authority == 'ledger'`, expected `'ledger_error_fail_closed'`. Root cause is not yet diagnosed; a test/import-alias issue has not been ruled out. |
| `test_market_slot_sequencing.py::test_19_agent_and_submission_remain_synchronized` | `config.py` mismatch. |
| `test_same_turn_deposit_sell.py::test_17_agent_and_submission_synchronized` | `config.py` mismatch. |
| `test_same_turn_sale_financing.py::test_21_agent_and_submission_synchronized` | `main.py` byte mismatch. |
| `test_same_turn_shed_relay.py::test_22_agent_and_submission_synchronized` | `main.py` SHA-256 mismatch. |

The five synchronization failures are baseline differences, not permission to overwrite protected production. The feed failure is a correctness-gate failure, not proof of a real-engine animal escape. Independent source audits additionally identify the workforce/reservation blockers above. The report received independent acquisition/P5 evidence review; its legacy $2,204 threshold wording was corrected following that review.
