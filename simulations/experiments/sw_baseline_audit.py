"""Read-only current baseline telemetry. Uses reused discovery seeds, never heldout.

Run with --run to execute seed 96401 x five opponents x both seats (10 games).
Records engine-successful transactions and actual unit-state changes, not intentions.
No production setting is changed. All policy imports come from submission/.
"""
from __future__ import annotations
import argparse
import copy
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'simulations/results/sw_architecture_audit'
OPPONENTS = ['pass', 'pure_wheat_rush', 'cow_milk_engine', 'melon_sniper', 'full_production_agent']


def quadrant(x, y):
    return ('N' if y < 5 else 'S') + ('W' if x < 5 else 'E')


def run_game(scenario):
    seed, opponent, seat = scenario
    assert not 98001 <= seed <= 98050
    sys.path[:0] = [str(ROOT / 'submission'), str(ROOT)]
    import kaggle_environments as ke
    import kaggle_environments.envs.kaggriculture.kaggriculture as kg
    import main
    import config
    from simulations.experiments.agent_zoo import get_agent
    assert not config.P51_T1_TWO_CYCLE_CARROT_ENABLED
    assert not config.P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED
    main.reset_agent_state()
    env = ke.make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed})
    env.reset()
    players = [main.agent, get_agent(opponent)]
    if seat:
        players.reverse()
    hourly, events, actions, eod = [], [], [], []
    step, pid = 0, -1
    current_farms = current_private = None
    originals = {n: getattr(kg, n) for n in ('_apply_unit_action', '_process_market', '_commit_unit', '_do_hire', '_do_buy_land', '_end_of_day', '_drop_inventories_to_shed')}

    def snapshot(farm, private):
        counts = Counter()
        for y, row in enumerate(farm['tiles']):
            for x, tile in enumerate(row):
                q = quadrant(x, y)
                if q not in farm['unlocked_quadrants']:
                    continue
                if tile is None:
                    counts[q + ':empty'] += 1
                elif isinstance(tile, dict):
                    if tile.get('kind') == 'PLANT':
                        crop = tile['crop']
                        counts[q + ':crop:' + crop] += 1
                        if tile.get('yield_units', 0) > 0:
                            counts[q + ':yield_present:' + crop] += 1
                            counts[q + ':yield_units:' + crop] += tile['yield_units']
                            if step // 24 - tile['planted_day'] >= kg.CROPS[crop]['first_yield_day']:
                                counts[q + ':mature:' + crop] += 1
                                counts[q + ':mature_units:' + crop] += tile['yield_units']
                        if not tile['watered_today']:
                            counts[q + ':unwatered'] += 1
                    elif 'animal' in tile:
                        counts[q + ':animal:' + tile['animal']] += 1
                        if not tile.get('fed_today'):
                            counts[q + ':unfed'] += 1
                    else:
                        counts[q + ':other:' + tile.get('kind', tile.get('structure', 'unknown'))] += 1
        carried = Counter()
        for inv in private['inventories']:
            carried.update(inv)
        return {'cash': farm['money'], 'workers': 1 + len(farm['hands']), 'unlocked': list(farm['unlocked_quadrants']), 'tiles': dict(counts), 'shed': dict(private['shed']), 'carried': dict(carried)}

    def apply(farm, private, idx, action, *args, **kwargs):
        nonlocal pid
        if idx == 0:
            pid += 1
        if pid != seat or idx >= len(private['inventories']):
            return originals['_apply_unit_action'](farm, private, idx, action, *args, **kwargs)
        pos = list(farm['farmer'] if idx == 0 else farm['hands'][idx - 1])
        x, y = pos
        before = copy.deepcopy((farm['tiles'][y][x], private['inventories'][idx], private['shed'], private['seeds']))
        originals['_apply_unit_action'](farm, private, idx, action, *args, **kwargs)
        after_pos = farm['farmer'] if idx == 0 else farm['hands'][idx - 1]
        after = (farm['tiles'][y][x], private['inventories'][idx], private['shed'], private['seeds'])
        op = action[0] if isinstance(action, list) and action else 'PASS'
        changed = before != after or pos != after_pos
        tile = before[0] if isinstance(before[0], dict) else {}
        record = {'step': step, 'worker': idx, 'q': quadrant(x, y), 'x': x, 'y': y, 'op': op, 'changed': changed, 'crop': tile.get('crop'), 'animal': tile.get('animal')}
        if op == 'PLANT' and changed:
            record['crop'] = action[1]
        for product in kg.PRODUCTS:
            diff = private['inventories'][idx].get(product, 0) - before[1].get(product, 0)
            if diff:
                record['inventory_delta_' + product] = diff
        actions.append(record)

    def market(state, env):
        nonlocal current_farms, current_private
        current_farms = state[0].observation.farms
        current_private = state[seat].observation.private
        return originals['_process_market'](state, env)

    def commit(op, item, price, farm, private, market, *args, **kwargs):
        ok = originals['_commit_unit'](op, item, price, farm, private, market, *args, **kwargs)
        if ok and private is current_private:
            events.append({'step': step, 'op': op, 'item': item, 'units': 1, 'cash': price if op == 'SELL' else -price})
        return ok

    def financial(name, op):
        def wrapper(farm, *args, **kwargs):
            before = farm['money']
            result = originals[name](farm, *args, **kwargs)
            if farm is current_farms[seat] and farm['money'] != before:
                events.append({'step': step, 'op': op, 'item': '', 'units': 1, 'cash': farm['money'] - before})
            return result
        return wrapper

    def drop(private, capacity):
        before = Counter(private['shed'])
        for inv in private['inventories']:
            before.update(inv)
        result = originals['_drop_inventories_to_shed'](private, capacity)
        if private is current_private:
            for product, units in (before - Counter(private['shed'])).items():
                events.append({'step': step, 'op': 'DISCARD', 'item': product, 'units': units, 'cash': 0})
        return result

    def end_day(state, env, day):
        farm, private = state[0].observation.farms[seat], state[seat].observation.private
        pre = snapshot(farm, private)
        old = copy.deepcopy(farm['tiles'])
        result = originals['_end_of_day'](state, env, day)
        deaths = Counter()
        for y, row in enumerate(old):
            for x, tile in enumerate(row):
                new = farm['tiles'][y][x]
                if isinstance(tile, dict) and tile.get('kind') == 'PLANT' and (not isinstance(new, dict) or new.get('kind') != 'PLANT'):
                    deaths[quadrant(x,y) + ':' + tile['crop']] += 1
        eod.append({'day': day, 'pre_refresh': pre, 'post_refresh': snapshot(farm, private), 'crop_deaths': dict(deaths)})
        return result

    kg._apply_unit_action, kg._process_market, kg._commit_unit = apply, market, commit
    kg._do_hire = financial('_do_hire', 'HIRE')
    kg._do_buy_land = financial('_do_buy_land', 'LAND')
    kg._end_of_day, kg._drop_inventories_to_shed = end_day, drop
    start = time.time()
    try:
        while not env.done:
            step = env.state[0].observation.step
            pid = -1
            pre = snapshot(env.state[0].observation.farms[seat], env.state[seat].observation.private)
            outputs = []
            for i, player in enumerate(players):
                try:
                    outputs.append(player(env.state[i].observation, env.configuration))
                except TypeError:
                    outputs.append(player(env.state[i].observation))
            env.step(outputs)
            post = snapshot(env.state[0].observation.farms[seat], env.state[seat].observation.private)
            hourly.append({'step': step, 'pre': pre, 'post': post})
    finally:
        for name, fn in originals.items():
            setattr(kg, name, fn)
    for row in hourly:
        cash_delta = sum(e['cash'] for e in events if e['step'] == row['step'])
        assert row['post']['cash'] - row['pre']['cash'] == cash_delta, row['step']
    assert hourly[-1]['post']['cash'] == 3000 + sum(e['cash'] for e in events)
    return {'seed': seed, 'opponent': opponent, 'seat': seat, 'score': hourly[-1]['post']['cash'], 'seconds': time.time()-start, 'engine_version': ke.__version__, 'engine_sha256': hashlib.sha256(Path(kg.__file__).read_bytes()).hexdigest(), 'policy_file': main.__file__, 'hours': hourly, 'actions': actions, 'events': events, 'eod': eod}


def export(games):
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    hour_rows, conservation, totals = [], [], []
    for game in games:
        all_events, all_actions = game['events'], game['actions']
        for product in ('WHEAT', 'FERTILIZER'):
            initial = game['hours'][0]['pre']['shed'].get(product, 0) + game['hours'][0]['pre']['carried'].get(product, 0)
            final = game['hours'][-1]['post']['shed'].get(product, 0) + game['hours'][-1]['post']['carried'].get(product, 0)
            bought = sum(e['units'] for e in all_events if e['op']=='BUY_PRODUCT' and e['item']==product)
            sold = sum(e['units'] for e in all_events if e['op']=='SELL' and e['item']==product)
            discarded = sum(e['units'] for e in all_events if e['op']=='DISCARD' and e['item']==product)
            acquired = sum(a.get('inventory_delta_'+product,0) for a in all_actions if a['op'] in ('HARVEST','COLLECT_FERTILIZER'))
            used = -sum(a.get('inventory_delta_'+product,0) for a in all_actions if a['op'] in ('FEED','FERTILIZE'))
            error = initial + bought + acquired - sold - discarded - used - final
            conservation.append(dict(seed=game['seed'],opponent=game['opponent'],seat=game['seat'],product=product,initial=initial,bought=bought,harvested_or_collected=acquired,sold=sold,discarded=discarded,used=used,final=final,residual=error))
            assert error == 0, conservation[-1]
        totals.append(dict(score=game['score'],actions=len(all_actions),moves=sum(a['op'] in ('NORTH','SOUTH','EAST','WEST') for a in all_actions),passes=sum(a['op']=='PASS' for a in all_actions),unchanged_nonpass=sum(not a['changed'] and a['op']!='PASS' for a in all_actions)))
        for hour in game['hours']:
            acts = [a for a in all_actions if a['step']==hour['step']]
            counts = Counter(a['op'] for a in acts)
            hr = {k:game[k] for k in ('seed','opponent','seat')}
            hr.update(step=hour['step'],day=hour['step']//24,hour=hour['step']%24,available_workers=hour['pre']['workers'],opening_cash=hour['pre']['cash'],closing_cash=hour['post']['cash'])
            hr.update({'actions:'+k:v for k,v in counts.items()})
            hr.update(hour['pre']['tiles'])
            hr.update({'shed:'+k:v for k,v in hour['pre']['shed'].items()})
            hr.update({'carried:'+k:v for k,v in hour['pre']['carried'].items()})
            hour_rows.append(hr)
        for day in range(30):
            hours = [h for h in game['hours'] if h['step']//24 == day]
            if not hours:
                continue
            acts = [a for a in game['actions'] if a['step']//24 == day]
            ev = [e for e in game['events'] if e['step']//24 == day]
            row = {k: game[k] for k in ('seed','opponent','seat')}
            row.update(day=day, opening_cash=hours[0]['pre']['cash'], closing_cash=hours[-1]['post']['cash'], available_actions=sum(h['pre']['workers'] for h in hours), attempted_actions=len(acts), moves=sum(a['op'] in ('NORTH','SOUTH','EAST','WEST') for a in acts), changed_actions=sum(a['changed'] for a in acts), no_change_nonpass=sum(not a['changed'] and a['op'] != 'PASS' for a in acts), pass_actions=sum(a['op']=='PASS' for a in acts))
            for event in ev:
                key = event['op'] + ':' + event['item']
                row[key + ':cash'] = row.get(key + ':cash', 0) + event['cash']
                row[key + ':units'] = row.get(key + ':units', 0) + event['units']
            for a in acts:
                key = a['q'] + ':' + a['op'] + ':' + (a['crop'] or a['animal'] or '')
                row[key + ':attempts'] = row.get(key + ':attempts', 0) + 1
                if a['changed']:
                    row[key + ':changed'] = row.get(key + ':changed', 0) + 1
                if a['op'] == 'HARVEST':
                    for key2, value in a.items():
                        if key2.startswith('inventory_delta_'):
                            key3 = a['q'] + ':harvest_units:' + key2.removeprefix('inventory_delta_')
                            row[key3] = row.get(key3, 0) + value
            for key in set(k for h in hours for k in h['pre']['tiles']):
                row['mean_tiles:'+key] = sum(h['pre']['tiles'].get(key,0) for h in hours)/len(hours)
            refresh = next((e for e in game['eod'] if e['day']==day),None)
            if refresh:
                for key,value in refresh['pre_refresh']['tiles'].items():
                    row['pre_refresh:'+key]=value
                for key,value in refresh['crop_deaths'].items():
                    row['actual_deaths:'+key]=value
            rows.append(row)
    for filename,data in [('current_baseline_daily.csv',rows),('current_baseline_hourly.csv',hour_rows),('physical_conservation.csv',conservation)]:
        fields = list(dict.fromkeys(k for row in data for k in row))
        with (OUT/filename).open('w', newline='') as f:
            writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader(); writer.writerows(data)
    summary={'n':len(games),'mean_cash':statistics.mean(g['score'] for g in games),'scenarios':[{k:g[k] for k in ('seed','opponent','seat','score','seconds','engine_version','engine_sha256','policy_file')} for g in games], 'interpretation':'State-changing actions are successful physical effects, not necessarily economically useful. yield_present includes immature initial yield; do not label mature without ripe_day. Daily cash is exact; hours and raw events retain all region and stock detail.'}
    summary['mean_actions']={k:statistics.mean(g[k] for g in totals) for k in totals[0]}
    summary['cash_categories_per_game']=dict(Counter())
    for game in games:
        for event in game['events']:
            key=event['op']+':'+event['item']
            summary['cash_categories_per_game'][key]=summary['cash_categories_per_game'].get(key,0)+event['cash']/len(games)
    summary['phase_means_per_game_day']={}
    for begin,end in [(0,5),(6,10),(11,15),(16,20),(21,29)]:
        phase=[r for r in rows if begin<=r['day']<=end]
        keys=[k for k in rows[0] if k not in ('seed','opponent','seat','day')]
        keys=list(dict.fromkeys(keys+[k for r in phase for k in r if k.startswith(('mean_tiles:','actual_deaths:','pre_refresh:'))]))
        summary['phase_means_per_game_day'][f'{begin}-{end}']={k:sum(r.get(k,0) for r in phase)/len(phase) for k in keys}
    summary['file_identity']=[{'file':p.relative_to(ROOT/'submission').as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'agent_equal':p.read_bytes()==(ROOT/'agent'/p.relative_to(ROOT/'submission')).read_bytes()} for p in (ROOT/'submission').rglob('*.py') if (ROOT/'agent'/p.relative_to(ROOT/'submission')).exists()]
    summary['limitations']=['One reused seed across five opponents and both seats; ten scenarios, not ten independent seed draws. No estimate of population improvement.', 'No cash reserve policy was changed. Cash is actual liquid treasury, not proof all future commitments covered.', 'Market revenue pooled across quadrants; exact sale-to-origin attribution requires inventory lots and is not identifiable here.', 'Engine stops after step718; day29 contains23hours and no final midnight refresh.', 'Mature counts in post snapshots at midnight use the pre-step day; use pre snapshots and pre_refresh for timing analysis.']
    (OUT/'current_baseline_summary.json').write_text(json.dumps(summary,indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--run',action='store_true'); parser.add_argument('--limit',type=int,default=10); parser.add_argument('--workers',type=int,default=4); args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if args.run:
        scenarios=[(96401,opp,seat) for opp in OPPONENTS for seat in (0,1)][:args.limit]
        games=[]
        with ProcessPoolExecutor(max_workers=args.workers,max_tasks_per_child=1) as pool:
            for future in as_completed([pool.submit(run_game,s) for s in scenarios]):
                game=future.result(); games.append(game)
                with gzip.open(OUT/f"baseline_{game['seed']}_{game['opponent']}_{game['seat']}.json.gz",'wt') as f: json.dump(game,f)
                print(game['seed'],game['opponent'],game['seat'],game['score'],round(game['seconds'],1),flush=True)
    else:
        games=[json.load(gzip.open(p,'rt')) for p in OUT.glob('baseline_*.json.gz')]
    export(games)
