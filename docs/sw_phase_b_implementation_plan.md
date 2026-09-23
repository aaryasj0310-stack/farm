# SW Phase B Implementation Plan: Minimal LIVE Prototype

**Status:** Proposed & Preregistered  
**Prerequisites:** Phase A Architectural Substrate & Shadow Harness Verified  

---

## 1. Minimal LIVE Prototype Scope

Phase B will transition the verified Phase A forward planning architecture from `SHADOW` to `LIVE` control in the smallest possible increment.

### Core Specifications for Phase B
1. **Strategic SW Target Day**:
   Target acquisition window set to **Day 8–9**.
2. **Workforce Schedule**:
   Initial hiring schedule **unchanged** from baseline (4 hands D0-5, 8 D6-9, 10 D10, 12 D11-29; total 13 workers with farmer). No unvalidated 14-hand flat hiring.
3. **Rapid Tranche Scaling**:
   - Tranche 1 (Immediate post-purchase): **8–12 contiguous crop tiles** (e.g. 4–6 Wheat + 4–6 Strawberry).
   - Tranche 2 (Day 10–11): **16 cumulative tiles** conditional on passing forward service certificate.
   - Tranche 3 (Day 12–13): **20–24 cumulative tiles**.
4. **Livestock Policy**:
   No mandatory new animals in SW initially. Existing livestock admissions preserved; conditional livestock considered only if spare pasture and feed buffers exist.
5. **No Hardcoded Crop Mix**:
   Crop portfolio selected from candidate tranches under certified forward labor and market price depression constraints.
6. **Scheduler Integration**:
   Activate soft locality with hard global deadline rescue, preventing both NE<->SW transit bouncing and P4.1 core worker displacement.

---

## 2. Controlled Verification Protocol (Phase B)

1. **Reused Diagnostic Panel**:
   Evaluate on 20 matched games across historical failure seeds to confirm zero starvation, zero crop death regressions, and verified SW production.
2. **Fresh Discovery Tournament**:
   10 fresh seeds $\times$ 5 diverse opponents $\times$ 2 seats = 100 matched pairs (200 games).
   - Paired cash delta target: $> +\$2,000$ mean with $95\%$ seed-cluster bootstrap CI $> 0$.
   - Operational safety gates: $> 98\%$ core retention, $0$ animal starvations, $0$ avoidable crop deaths.
3. **Protected Seeds Quarantine**:
   Evaluation seeds `98001–98050` remain strictly untouched until final post-discovery validation.
