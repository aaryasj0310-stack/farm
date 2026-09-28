import json
import numpy as np

with open('simulations/results/phase_sw_c1/sw_c1_matches_discovery.json') as f:
    disc = json.load(f)
with open('simulations/results/phase_sw_c1/sw_c1_matches_confirmation.json') as f:
    conf = json.load(f)

all_matches = disc + conf
print(f'Total matches: {len(all_matches)}')

crops_planted = {}
rejection_reasons = {}
deltas_fc = []
exp_days = []

for m in all_matches:
    for exp in m.get('sw_expansion_history', []):
        crop = exp.get('crop')
        crops_planted[crop] = crops_planted.get(crop, 0) + 1
        if 'delta_fc' in exp:
            deltas_fc.append(exp['delta_fc'])
        if 'day' in exp:
            exp_days.append(exp['day'])
    for rej in m.get('sw_expansion_rejections', []):
        r_type = rej.get('reason', 'UNKNOWN')
        # summarize reason category
        cat = r_type.split(':')[0] if ':' in r_type else r_type
        rejection_reasons[cat] = rejection_reasons.get(cat, 0) + 1

print(f'\nTotal Expansions Approved: {sum(crops_planted.values())}')
print(f'Crops chosen for expansion: {crops_planted}')
if deltas_fc:
    print(f'Marginal Delta FC: Mean=${np.mean(deltas_fc):.2f}, Min=${np.min(deltas_fc):.2f}, Max=${np.max(deltas_fc):.2f}')
if exp_days:
    print(f'Expansion Days: Mean={np.mean(exp_days):.1f}, Min={np.min(exp_days)}, Max={np.max(exp_days)}')
print(f'Rejection reasons count: {rejection_reasons}')
