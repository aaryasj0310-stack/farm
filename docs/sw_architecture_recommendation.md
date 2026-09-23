# SW architecture recommendation

Date: 2026-09-23. Status: PROPOSED and unimplemented.

Adopt a forward-committed, crop-led SW architecture with a conditional feed variant. Start with Architecture A from sw_architecture_alternatives.md, but admit only the smaller SW cohort that passes an hourly service certificate; keep Architecture C as the first ablation. Do not make the 14-hand schedule or extra livestock the default.

P4.1 transferred two productive core workers into SW and lost $4,819.10/game; core agricultural attempts fell 111.6/game for those workers and watering compliance fell 4.45 points. P1.1 improved $11,053.85 relative to rigid P1 but remained $8,790.55 below its control. Saved leaders acquired NE around D5 and SW around D8-9, developed mixed SW crops within days, and reached 13 total workers by D12. This is timing evidence, not causal proof.

Reserve capital and dated crop cohorts from D0. Target NE D3-5 when its gate is met. Prepare SW funding, seed tranches and labor by D6-8; buy only when three days of planting/watering, existing feed, wages and core deadlines fit. Start with 8-12 contiguous SW tiles, then expand after one full harvest/market cycle. Keep the early herd and feed commitments. Decline future animals only when their lost wool/milk/fertilizer is included in the same waterfall.

Later implementation changes: replace isolated should_buy_land ROI with a forward commitment covering land, seeds, wages, feed, cohort deadlines, shed capacity and market supply; extend MacroPlanner to compare whole-farm with/without trajectories; add a region/time-indexed service certificate to task_scheduler; add cohort/lot and successful-action telemetry; keep submission synchronized with agent and assert default-off flags. P51 and P61 remain disabled.

Modeled A sensitivity is $4.8k/$10.4k/$14.5k; C is $5.0k/$7.5k/$13.6k; B is -$0.7k/$7.6k/$11.5k; C+ is $5.6k/$16.9k/$26.0k in weak/moderate/strong stock cases. These are scenario rows, not statistical intervals. A full 24-tile plan still has an unresolved 1,351-action routing budget, so a smaller first tranche is recommended.

Invalidate the recommendation if matched runs show negative paired cash, preserved core output falls beyond the gate, hourly deadlines fail, price effects erase contribution, early reserves delay NE or animals, or the design needs unvalidated 14-hand/extra-cow assumptions to remain solvent. Select another complete architecture rather than loosening a land threshold.
