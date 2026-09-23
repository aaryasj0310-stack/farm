"""Read-only saved replay census and P4.1 measurement audit. No simulations/seeds run.

Run from repository root: python simulations/experiments/sw_leader_audit.py
Actions at replay step i produced observation i; positions come from i-1.
Public state supports crops/geography; market orders are requests, not settlements.
"""
import json
from collections import Counter
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'simulations/experiments/results/sw_leader_audit'


def quad(x, y):
    return ('N' if y < 5 else 'S') + ('W' if x < 5 else 'E')


def count_tiles(farm):
    result = Counter()
    for y, row in enumerate(farm['tiles']):
        for x, tile in enumerate(row):
            if isinstance(tile, dict):
                q = quad(x, y)
                if tile.get('crop'):
                    result[f'{q}:crop:{tile["crop"]}'] += 1
                if tile.get('animal'):
                    result[f'{q}:animal:{tile["animal"]}'] += 1
                if tile.get('kind') in ('PASTURE', 'COOP'):
                    result[f'{q}:structure:{tile["kind"]}'] += 1
    return dict(result)


def player(data, seat):
    out = dict(seat=seat, name=data.get('info', {}).get('TeamNames', ['?', '?'])[seat],
               score=data['steps'][-1][seat].get('reward'), purchases={}, daily=[],
               actions=Counter(), harvest_inventory_increase=Counter(),
               market_requested_units=Counter(), worker_quadrant_hours=Counter(),
               crop_tile_hours=Counter(), move_distance=0, first_sw_half_cropped=None)
    for i, step in enumerate(data['steps']):
        obs = step[seat]['observation']
        # Some compact replays omit shared fields from seat 1.
        shared = step[0]['observation']
        farms = obs.get('farms', shared.get('farms'))
        if not farms:
            continue
        farm = farms[seat]
        day, hour = obs.get('day', shared.get('day')), obs.get('hour', shared.get('hour'))
        tiles = count_tiles(farm)
        for k, v in tiles.items():
            if ':crop:' in k:
                out['crop_tile_hours'][k] += v
        for pos in [farm['farmer']] + farm.get('hands', []):
            out['worker_quadrant_hours'][quad(*pos)] += 1
        for q in ('NE', 'SW', 'SE'):
            if q in farm.get('unlocked_quadrants', []) and q not in out['purchases']:
                prev = data['steps'][max(0, i-1)][0]['observation'].get('farms', farms)[seat]
                out['purchases'][q] = dict(first_observation=[day,hour], workers_before=1+len(prev.get('hands',[])), workers_after=1+len(farm.get('hands',[])))
        if sum(v for k,v in tiles.items() if k.startswith('SW:crop:')) >= 12 and out['first_sw_half_cropped'] is None:
            out['first_sw_half_cropped'] = [day,hour]
        if hour == 23 or i == len(data['steps'])-1:
            out['daily'].append(dict(day=day,hour=hour,cash=farm['money'], workers=1+len(farm.get('hands', [])),tiles=tiles,
                animal_positions=[dict(x=x,y=y,animal=t['animal']) for y,row in enumerate(farm['tiles']) for x,t in enumerate(row) if isinstance(t,dict) and t.get('animal')],
                structures=[dict(x=x,y=y,kind=t['kind']) for y,row in enumerate(farm['tiles']) for x,t in enumerate(row) if isinstance(t,dict) and t.get('kind') in ('PASTURE','COOP')]))
        if not i:
            continue
        prevstep = data['steps'][i-1]
        prevobs = prevstep[seat]['observation']
        prevfarm = prevobs.get('farms', prevstep[0]['observation'].get('farms'))[seat]
        positions = [prevfarm['farmer']] + prevfarm.get('hands', [])
        action = step[seat].get('action') or {}
        if not isinstance(action, dict):
            continue
        acts = [action.get('farmer', ['PASS'])] + action.get('hands', [])
        inv0 = prevobs.get('private',{}).get('inventories', [])
        inv1 = obs.get('private',{}).get('inventories', [])
        for u,(pos,a) in enumerate(zip(positions,acts)):
            if not a: continue
            op = a[0]
            q = quad(*pos)
            out['actions'][f'{q}:{op}'] += 1
            current_positions = [farm['farmer']] + farm.get('hands', [])
            if u < len(current_positions) and hour != 0:
                out['move_distance'] += sum(abs(v-w) for v,w in zip(pos,current_positions[u]))
            if op == 'HARVEST' and hour != 0 and u < min(len(inv0),len(inv1)):
                for product,n in inv1[u].items():
                    delta = n-inv0[u].get(product,0)
                    if delta > 0:
                        out['harvest_inventory_increase'][f'{q}:{product}'] += delta
        for a in action.get('market', []):
            if len(a)>=3 and a[0] in ('BUY_PRODUCT','SELL','BUY_SEED','BUY_ANIMAL'):
                out['market_requested_units'][f'{a[0]}:{a[1]}'] += a[2]
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    seen, rows, skipped, duplicates = set(), [], [], []
    for path in sorted((ROOT/'replays').rglob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data,dict) or 'steps' not in data:
            skipped.append(str(path.relative_to(ROOT))); continue
        eid = str(data.get('info',{}).get('EpisodeId',data.get('id',path.stem)))
        if eid in seen:
            duplicates.append(str(path.relative_to(ROOT))); continue
        seen.add(eid)
        record = dict(episode=eid,path=str(path.relative_to(ROOT)),module_version=data.get('module_version'),
                      configuration=data.get('configuration'),players=[player(data,s) for s in range(2)])
        (OUT/f'{eid}.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        rows.append({**{k:v for k,v in record.items() if k!='players'},'players':[{k:v for k,v in p.items() if k!='daily'} for p in record['players']]})
    (OUT/'summary.json').write_text(json.dumps(dict(replays=rows,duplicates=duplicates,non_replay_files=skipped),indent=2),encoding='utf-8')
    p41=json.loads((ROOT/'simulations/experiments/results/p41_feasibility_test.json').read_text())
    audit={}
    for arm in ('Control','Treatment'):
        rr=[r for r in p41['raw_results'] if r['arm']==arm]
        audit[arm]={k:mean(r[k] for r in rr) for k in ('final_cash','watering_compliance','core_plant_deaths','missed_feedings')}
        for key in ('core_agri_actions','sw_agri_actions','sw_harvest_units'):
            c=Counter()
            for r in rr:c.update(r[key])
            audit[arm][key+'_panel_total']=dict(c)
            audit[arm][key+'_per_game']={k:v/len(rr) for k,v in c.items()}
    assert round(audit['Treatment']['final_cash']-audit['Control']['final_cash'],2)==-4819.10
    assert quad(0,5)=='SW' and quad(5,4)=='NE'
    (OUT/'p41_recomputed.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print(json.dumps(dict(unique_replays=len(rows),duplicates=len(duplicates),players=len(rows)*2,p41=audit),indent=2))


if __name__=='__main__':main()
