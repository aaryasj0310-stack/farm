"""Read-only engine-derived SW sensitivity model; no agent or seed execution.

Run with the repository's Python 3.12. Outputs arithmetic scenarios, NOT wins.
"""
import ast
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = Path('C:/Users/rohit/AppData/Local/Programs/Python/Python312/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py')
OUT = ROOT / 'artifacts/sw_economics'


def load_engine():
    source = ENGINE.read_text(encoding='utf-8')
    tree = ast.parse(source)
    # Execute engine constants/functions, but no imports, rendering, or environment.
    names = {'CROPS', 'ANIMALS', 'MARKET_I0', 'PRICE_FLOOR', 'MARKET_PARAMS',
             'HINGE_GAIN', 'FARM_HAND_COST_MULT'}
    funcs = {'_shape', 'market_price', '_fib', '_hire_cost', '_new_plant',
             '_new_animal', '_daily_refresh_plants', '_daily_refresh_animals'}
    body = [n for n in tree.body if
            (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets))
            or (isinstance(n, ast.FunctionDef) and n.name in funcs)]
    namespace = {'math': math}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(ENGINE), 'exec'), namespace)
    return namespace, hashlib.sha256(source.encode()).hexdigest()


def sale(e, product, quantity, inventory):
    revenue = 0
    for _ in range(quantity):
        price = e['market_price'](product, inventory)
        revenue += price
        inventory += price > 1
    return revenue


def animal(e, species, placed):
    farm = {'tiles': [[e['_new_animal'](species, placed)]]}
    units = feed = care = fertilizer = harvest = 0
    for day in range(placed, 30):
        tile = farm['tiles'][0][0]
        if tile['yield_units']:
            units += tile['yield_units']
            harvest += 1
            tile['yield_units'] = 0
        if day == 29:
            break
        if tile['fertilizer_available']:
            fertilizer += 1
            tile['fertilizer_available'] = False
        tile['fed_today'] = tile['cared_today'] = True
        feed += 1
        care += 1
        e['_daily_refresh_animals'](farm, day)
    return dict(units=units, feed=feed, care=care, fertilizer=fertilizer,
                harvest=harvest, direct_actions=3+feed+care+fertilizer+harvest)


def main():
    e, digest = load_engine()
    OUT.mkdir(parents=True, exist_ok=True)
    costs = {n: sum(e['_hire_cost'](i) for i in range(n)) for n in range(4, 17)}
    # These minimum-water calendars give max unfertilized output and survival.
    water = {'WHEAT': [0,2,3,4], 'CARROT': [0,2,3],
             'MELON': [0,2,4,6,7,8,9,10],
             'TOMATO': [0,2,4,6,8,10],
             'STRAWBERRY': list(range(0,16,2))}
    duration = {'WHEAT':4, 'CARROT':3, 'MELON':10, 'TOMATO':11, 'STRAWBERRY':16}
    expected = {'WHEAT':4, 'CARROT':3, 'MELON':6, 'TOMATO':4, 'STRAWBERRY':4}
    crops = {}
    for crop, days in water.items():
        tile = e['_new_plant'](crop, 0, 24)
        farm = {'tiles':[[tile]]}
        for day in range(duration[crop]+1):
            if day in days:
                tile['watered_today'] = True
                cd = e['CROPS'][crop]
                if not cd['ongoing'] and (cd['max_yield_day']+1)//2 <= day <= cd['max_yield_day']:
                    tile['yield_units'] = min(cd['max_yield'], tile['yield_units']+1)
            if day == duration[crop]:
                assert tile['yield_units'] == expected[crop], (crop, tile)
                break
            e['_daily_refresh_plants'](farm, day, 24)
            assert farm['tiles'][0][0]['kind'] == 'PLANT'
        actions = 2+len(days)+int(e['CROPS'][crop]['ongoing'])
        seed = e['CROPS'][crop]['seed']
        base = e['MARKET_PARAMS'][crop]['base']
        net = expected[crop]*base-seed
        crops[crop] = dict(units=expected[crop], elapsed_days=duration[crop],
                           occupied_calendar_days=duration[crop]+1, water_days=days,
                           direct_actions=actions, seed_cost=seed, base_reference_net=net,
                           net_per_occupied_tile_day=net/(duration[crop]+1),
                           net_per_direct_action=net/actions, net_per_seed_dollar=net/seed)
    # Three cohorts start d6/7/8; same-tile replant next day prevents scheduling fiction.
    events = []
    for count, start in [(3,6),(3,7),(2,8)]:
        for crop, starts in [('MELON',[start,start+11]), ('STRAWBERRY',[start]),
                             ('WHEAT',[start,start+5,start+10,start+15])]:
            for planted in starts:
                events.append((crop,count,planted))
        events.append(('WHEAT',count,start+17))  # after strawberry harvest
        if start+23 <= 29:
            events.append(('CARROT',count,start+20)) # only earliest cohort fits
    daily = [dict(day=d, plant=0,water=0,harvest=0,dig=0,units={},seed_cost=0) for d in range(30)]
    quantities = {c:0 for c in e['CROPS']}
    for crop,count,start in events:
        end = start+duration[crop]
        assert end <= 29, (crop,start,end)
        daily[start]['plant'] += count
        daily[start]['seed_cost'] += count*e['CROPS'][crop]['seed']
        for offset in water[crop]:
            daily[start+offset]['water'] += count
        daily[end]['harvest'] += count
        daily[end]['units'][crop] = daily[end]['units'].get(crop,0)+count*expected[crop]
        quantities[crop] += count*expected[crop]
        if e['CROPS'][crop]['ongoing']:
            daily[end]['dig'] += count  # after final harvest, before next-day replant
    for row in daily:
        row['direct_actions'] = row['plant']+row['water']+row['harvest']+row['dig']
        # Explicit planning allowance, not measured route execution.
        row['route_allowance'] = 30 if row['direct_actions'] else 0
        row['deposit_allowance'] = 8 if row['harvest'] else 0
        row['total_budget'] = row['direct_actions']+row['route_allowance']+row['deposit_allowance']
        row['available_hours_per_early_hired_hand'] = 22 if row['day']==29 else 23
        row['worker_lower_bound'] = math.ceil(row['total_budget']/row['available_hours_per_early_hired_hand'])
    seed_cost = sum(r['seed_cost'] for r in daily)
    ref = {'WHEAT':36.45,'CARROT':40.10,'TOMATO':74.55,'STRAWBERRY':248.81,'MELON':238.43}
    reference_revenue = sum(q*ref[c] for c,q in quantities.items())
    sensitivities = []
    for offset in [-200,-100,0,50]:
        revenues = {c:sale(e,c,q,10000+offset) for c,q in quantities.items() if q}
        sensitivities.append(dict(initial_inventory_offset=offset,revenue_by_product=revenues,
                                  total_revenue=sum(revenues.values()),
                                  net_after_land_seeds_early_hiring=sum(revenues.values())-seed_cost-2000-497))
    animals = {species: {str(day):animal(e,species,day) for day in [4,6,10,14]}
               for species in e['ANIMALS']}
    # A stock-only whole-farm sensitivity, not a time-resolved market forecast.
    # Wheat is net sales-minus-buys (round-trip churn cannot be counted as output).
    baseline = {'WHEAT':148,'CARROT':69,'TOMATO':23,'STRAWBERRY':76,
                'MELON':91,'MILK':143,'WOOL':72,'FERTILIZER':188}
    demand_cases = {
        'weak': {'WHEAT':100,'CARROT':30,'TOMATO':30,'STRAWBERRY':30,'MELON':30,'MILK':30,'WOOL':30,'FERTILIZER':0},
        'moderate': {'WHEAT':300,'CARROT':150,'TOMATO':100,'STRAWBERRY':200,'MELON':30,'MILK':200,'WOOL':150,'FERTILIZER':0},
        'strong': {'WHEAT':600,'CARROT':400,'TOMATO':200,'STRAWBERRY':400,'MELON':30,'MILK':400,'WOOL':400,'FERTILIZER':0}}
    # A omits two prospective d14 sheep; it never starves/removes owned animals.
    a_delta = dict(quantities, WOOL=-36,FERTILIZER=-28)
    a_delta['WHEAT'] += 30
    architectures = {
        'A_selective_crop': (a_delta,dict(land=2000,seeds=2540,hires=497,animals=-1000)),
        'B_labor_scaled': (quantities,dict(land=2000,seeds=2540,hires=12087,animals=0)),
        'C_feed_only': ({'WHEAT':384,'CARROT':27},dict(land=2000,seeds=1140,hires=497,animals=0)),
        'C_feed_two_cows_d10': ({'WHEAT':346,'CARROT':27,'MILK':42,'FERTILIZER':36},dict(land=2000,seeds=1140,hires=497,animals=800))}
    whole_farm=[]
    for name,(delta,expenses) in architectures.items():
        for case,demand in demand_cases.items():
            revenue_delta={}
            core_price_effect={}
            quantity_effect={}
            for crop,q in delta.items():
                old=baseline[crop]; new=old+q; stock=10000-demand[crop]
                r0=sale(e,crop,old,stock); r1=sale(e,crop,new,stock)
                revenue_delta[crop]=r1-r0
                core_price_effect[crop]=old*(r1/new-r0/old) if new else -r0
                quantity_effect[crop]=q*r1/new if new else 0
            whole_farm.append(dict(architecture=name,case=case,net_quantity_delta=delta,
                revenue_delta=revenue_delta,core_price_effect=core_price_effect,
                quantity_effect=quantity_effect,expenses=expenses,
                net=sum(revenue_delta.values())-sum(expenses.values())))
    timing=[]
    for bought in range(6,11):
        qty={c:0 for c in e['CROPS']}; seeds=actions=0
        for count,start in [(3,bought),(3,bought+1),(2,bought+2)]:
            plans=[('MELON',[start,start+11]),('STRAWBERRY',[start]),
                   ('WHEAT',[start,start+5,start+10,start+15,start+17]),
                   ('CARROT',[start+20])]
            for crop,starts in plans:
                for planted in starts:
                    if planted+duration[crop] <= 29:
                        qty[crop]+=count*expected[crop]
                        seeds+=count*e['CROPS'][crop]['seed']
                        actions+=count*(2+len(water[crop])+int(e['CROPS'][crop]['ongoing']))
        gross=sum(q*ref[c] for c,q in qty.items())
        timing.append(dict(buy_day=bought,quantities=qty,seed_cost=seeds,
                           direct_actions=actions,reference_gross=gross,
                           reference_net_before_displacement=gross-seeds-2000-497))
    assert costs[12] == 376 and costs[14]-costs[12] == 610
    assert quantities == {'WHEAT':160,'CARROT':9,'TOMATO':0,'STRAWBERRY':32,'MELON':96}
    assert animals['COW']['6']['units'] == 27
    result = dict(engine_path=str(ENGINE),engine_sha256=digest,
                  classification='engine arithmetic and explicit counterfactual assumptions; no simulations',
                  daily_hire_cost=costs,crops=crops,animals=animals,
                  whole_farm_stock_sensitivities=whole_farm,demand_cases=demand_cases,
                  stock_model_baseline_net_units=baseline,portfolio=dict(
                      quantities=quantities,seed_cost=seed_cost,reference_revenue=reference_revenue,
                      direct_actions=sum(r['direct_actions'] for r in daily),
                      budget_actions=sum(r['total_budget'] for r in daily),
                      peak_workers=max(r['worker_lower_bound'] for r in daily),
                      sensitivities=sensitivities),timing_sensitivity=timing)
    (OUT/'model.json').write_text(json.dumps(result,indent=2)+'\n')
    with (OUT/'day_action_budget.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(daily[0]))
        writer.writeheader(); writer.writerows(daily)
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
