"""Same-seed package benchmark with isolated agent processes and engine telemetry."""
import argparse
from collections import Counter
import contextlib
import copy
import hashlib
import importlib.util
import json
import multiprocessing as mp
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'simulations/results/score_gap_20260911'
MOVES = {'MOVE', 'NORTH', 'SOUTH', 'EAST', 'WEST'}


def source_hash(path):
    digest = hashlib.sha256()
    for file in sorted(path.rglob('*.py')):
        digest.update(file.relative_to(path).as_posix().encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


def worker(pipe, source):
    source = Path(source)
    spec = importlib.util.spec_from_file_location('benchmark_agent', source / 'main.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    trace = []
    macro = sys.modules[module.MacroPlanner.__module__]
    original_gate = macro.should_buy_land
    original_build = module.OrderBuilder.build
    current = [None]

    def gate(*args, **kwargs):
        result = original_gate(*args, **kwargs)
        if current[0] and 8 <= current[0]['day'] <= 13:
            trace.append({'type': 'land_gate', 'quadrant': args[0], 'decision': result[0],
                          'reason': result[1], 'diagnostics': result[2], 'money': args[2],
                          'costs': kwargs})
        return result

    def build(self, ctx, intents):
        result = original_build(self, ctx, intents)
        if current[0] and 8 <= current[0]['day'] <= 13:
            trace.append({'type': 'order_builder', 'intents': copy.deepcopy(intents),
                          'orders': result[0], 'ledger': result[1]})
        return result

    macro.should_buy_land = gate
    module.OrderBuilder.build = build
    while True:
        payload = pipe.recv()
        if payload is None:
            return
        obs, config = payload
        current[0] = obs
        trace.clear()
        try:
            action = module.agent(obs, config)
            pipe.send((action, module.get_last_fallback_diagnostic(), json.loads(json.dumps(trace, default=str))))
        except Exception as exc:
            pipe.send((None, repr(exc), trace))


def run_game(make, engine, candidate, opponent, seed):
    pipes, processes = [], []
    for source in (candidate, opponent):
        parent, child = mp.Pipe()
        proc = mp.Process(target=worker, args=(child, str(source)))
        proc.start()
        pipes.append(parent)
        processes.append(proc)
    counts = Counter()
    daily = {}
    fallbacks = []
    metrics = Counter()
    sw_samples = []
    sw_day = None
    sw_breakdowns = []
    land_purchases = {}
    first_sw_events = {}
    gate_trace = []
    env = make('kaggriculture', configuration={'seed': seed, 'loglevel': 'ERROR', 'episodeSteps': 721})
    originals = {name: getattr(engine, name) for name in
                 ('_daily_refresh_animals', '_daily_refresh_plants', '_decay_plants', '_apply_unit_action')}
    target = [None]
    current_day = [0]
    current_hour = [0]
    original_interpreter = env.interpreter

    def interpreter(state, environment):
        if state[0].observation.get('farms'):
            target[0] = state[0].observation.farms[0]
        before = set(target[0]['unlocked_quadrants']) if target[0] else set()
        result = original_interpreter(state, environment)
        if target[0]:
            for quadrant in set(target[0]['unlocked_quadrants']) - before:
                land_purchases[quadrant] = {'day': current_day[0], 'hour': current_hour[0]}
        return result

    env.interpreter = interpreter

    def track_refresh(name, farm, *args, **kwargs):
        selected = farm is target[0]
        before = copy.deepcopy(farm['tiles']) if selected else None
        if selected and name == '_daily_refresh_animals':
            missed = sum(isinstance(t, dict) and 'animal' in t and not t['fed_today'] for row in before for t in row)
            metrics['missed_feeds'] += missed
            metrics['missed_feeds_terminal' if current_day[0] == 29 else 'missed_feeds_preterminal'] += missed
            daily.setdefault(str(current_day[0]), {})['missed_feeds'] = missed
        result = originals[name](farm, *args, **kwargs)
        if selected:
            for y, row in enumerate(before):
                for x, old in enumerate(row):
                    new = farm['tiles'][y][x]
                    if not isinstance(old, dict):
                        continue
                    if name == '_daily_refresh_animals' and 'animal' in old and not (isinstance(new, dict) and 'animal' in new):
                        metrics['animal_deaths'] += 1
                    if old.get('kind') == 'PLANT' and isinstance(new, dict) and new.get('kind') == 'WEED':
                        metrics['crop_deaths' if name == '_daily_refresh_plants' else 'crop_lifecycle_expirations'] += 1
        return result

    def unit(farm, private, idx, action, *args, **kwargs):
        if farm is not target[0]:
            return originals['_apply_unit_action'](farm, private, idx, action, *args, **kwargs)
        old = (copy.deepcopy(farm), copy.deepcopy(private))
        result = originals['_apply_unit_action'](farm, private, idx, action, *args, **kwargs)
        op = action[0] if isinstance(action, list) and action else 'PASS'
        counts[op] += 1
        day_counts = daily.setdefault(str(current_day[0]), {}).setdefault('actions', {})
        day_counts[op] = day_counts.get(op, 0) + 1
        metrics['available_actions'] += 1
        changed = old != (farm, private)
        old_pos = old[0]['farmer'] if idx == 0 else old[0]['hands'][idx-1]
        new_pos = farm['farmer'] if idx == 0 else farm['hands'][idx-1]
        was_sw = old_pos[0] < 5 and old_pos[1] >= 5
        now_sw = new_pos[0] < 5 and new_pos[1] >= 5
        if op in MOVES:
            if was_sw and now_sw:
                metrics['sw_movement_within'] += 1
            elif was_sw:
                metrics['sw_movement_from'] += 1
            elif now_sw:
                metrics['sw_movement_to'] += 1
        if was_sw and op == 'PASS':
            metrics['sw_idle_actions'] += 1
        if changed and was_sw:
            tile = farm['tiles'][old_pos[1]][old_pos[0]]
            event = 'planting' if op == 'PLANT' else 'pasture' if op == 'BUILD_PASTURE' else 'animal' if isinstance(tile, dict) and 'animal' in tile and not (isinstance(old[0]['tiles'][old_pos[1]][old_pos[0]], dict) and 'animal' in old[0]['tiles'][old_pos[1]][old_pos[0]]) else None
            if event and event not in first_sw_events:
                first_sw_events[event] = {'day': current_day[0], 'hour': current_hour[0]}
        if changed and op not in MOVES:
            metrics['productive_actions'] += 1
        if not changed and op != 'PASS':
            metrics['ineffective_actions'] += 1
        return result

    for name in originals:
        if name == '_apply_unit_action':
            setattr(engine, name, unit)
        else:
            setattr(engine, name, lambda farm, *a, _name=name, **kw: track_refresh(_name, farm, *a, **kw))

    def act(player):
        def wrapped(obs, config):
            nonlocal sw_day
            if player == 0:
                current_day[0] = obs['day']
                current_hour[0] = obs['hour']
                farm = obs['farms'][0]
                if 'SW' in farm['unlocked_quadrants']:
                    if sw_day is None:
                        sw_day = obs['day']
                    active = sum(isinstance(farm['tiles'][y][x], dict) and farm['tiles'][y][x].get('kind') in ('PLANT', 'COOP', 'PASTURE') for y in range(5,10) for x in range(5))
                    sw_samples.append(active / 25)
                    breakdown = Counter()
                    for y in range(5, 10):
                        for x in range(5):
                            tile = farm['tiles'][y][x]
                            key = 'empty' if tile is None else 'locked' if tile == 'LOCKED' else 'animal_' + tile['animal'] if 'animal' in tile else 'crop_' + tile['crop'] if 'crop' in tile else 'empty_pasture' if tile.get('kind') == 'PASTURE' else tile.get('kind', 'other').lower()
                            breakdown[key] += 1
                    sample = {'day': obs['day'], 'hour': obs['hour'], **dict(breakdown)}
                    sw_breakdowns.append(sample)
                    daily.setdefault(str(obs['day']), {}).setdefault('sw_samples', []).append(sample)
                if obs['hour'] == 23:
                    daily.setdefault(str(obs['day']), {}).update(money=farm['money'], unlocked=farm['unlocked_quadrants'], tiles=dict(Counter(t.get('animal') or t.get('crop') or t['kind'] for row in farm['tiles'] for t in row if isinstance(t, dict))), shed=dict(obs['private']['shed']))
            pipes[player].send((json.loads(json.dumps(obs)), dict(config)))
            action, diagnostic, trace = pipes[player].recv()
            if player == 0 and 8 <= obs['day'] <= 13:
                gate_trace.append({'day': obs['day'], 'hour': obs['hour'], 'money': farm['money'],
                                   'unlocked': list(farm['unlocked_quadrants']), 'hands': len(farm['hands']),
                                   'shed': dict(obs['private']['shed']), 'seeds': dict(obs['private'].get('seeds', {})),
                                   'animals': dict(Counter(t['animal'] for row in farm['tiles'] for t in row if isinstance(t, dict) and 'animal' in t)),
                                   'trace': trace, 'emitted_market': action.get('market', []) if action else []})
            if player == 0 and action:
                metrics['emitted_market_orders'] += len(action.get('market', []))
                metrics['market_order_limit_violations'] += int(len(action.get('market', [])) > 10)
            if diagnostic:
                fallbacks.append({'player': player, 'day': obs['day'], 'hour': obs['hour'], 'diagnostic': diagnostic})
            if action is None:
                raise RuntimeError(diagnostic)
            return action
        return wrapped

    start = time.perf_counter()
    try:
        env.run([act(0), act(1)])
        final = env.steps[-1]
        status = [s.status for s in final]
        obs = final[0].observation
        if obs.day != 30 or any(s != 'DONE' for s in status):
            print(json.dumps(env.logs[-2:], default=str), file=sys.stderr)
            raise RuntimeError(f'Incomplete game: {obs.day=} {obs.hour=} {status=}')
        purchase = land_purchases.get('SW')
        delay = {key: ((event['day']-purchase['day'])*24 + event['hour']-purchase['hour']) for key,event in first_sw_events.items()} if purchase else {}
        sw_means = {key: sum(s.get(key, 0) for s in sw_breakdowns)/len(sw_breakdowns) for key in set().union(*(s.keys() for s in sw_breakdowns)) - {'day','hour'}} if sw_breakdowns else {}
        return {'seed': seed, 'score': obs.farms[0]['money'], 'opponent_score': obs.farms[1]['money'],
                'land_purchases': land_purchases, 'sw_first_events': first_sw_events, 'sw_event_delay_hours': delay,
                'sw_mean_tile_counts': sw_means, 'sw_empty_tile_days': sum(s.get('empty',0) for s in sw_breakdowns)/24,
                'sw_unused_tile_days': sum(s.get('empty',0)+s.get('weed',0)+s.get('empty_pasture',0)+s.get('coop',0) for s in sw_breakdowns)/24,
                'gate_trace': gate_trace,
                'terminal_day': obs.day, 'steps': len(env.steps), 'statuses': status,
                'seconds': round(time.perf_counter()-start, 2), 'sw_purchase_day': sw_day,
                'sw_utilization': sum(sw_samples)/len(sw_samples) if sw_samples else None,
                'action_utilization': metrics['productive_actions']/metrics['available_actions'],
                'travel_share': sum(counts[op] for op in MOVES)/metrics['available_actions'], 'idle_actions': counts['PASS'],
                **dict(metrics), 'animal_deaths': metrics['animal_deaths'], 'missed_feeds': metrics['missed_feeds'],
                'crop_deaths': metrics['crop_deaths'], 'actions': dict(counts), 'daily': daily, 'fallbacks': fallbacks}
    finally:
        for name, original in originals.items():
            setattr(engine, name, original)
        for pipe, proc in zip(pipes, processes):
            pipe.send(None)
            proc.join(timeout=10)
            if proc.is_alive():
                proc.terminate()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['before', 'after'], required=True)
    parser.add_argument('--seeds', nargs='+', type=int, default=[11,101,202,303,404])
    parser.add_argument('--results-dir', type=Path, default=RESULTS)
    args = parser.parse_args()
    results = args.results_dir
    results.mkdir(parents=True, exist_ok=True)
    baseline = results / 'before'
    if not baseline.exists():
        shutil.copytree(ROOT / 'submission', baseline, ignore=shutil.ignore_patterns('__pycache__'))
    candidate = results / args.phase
    if not candidate.exists():
        shutil.copytree(ROOT / 'submission', candidate, ignore=shutil.ignore_patterns('__pycache__'))
    with contextlib.redirect_stdout(sys.stderr):
        from kaggle_environments import make
        from kaggle_environments.envs.kaggriculture import kaggriculture as engine
    result = {'source_sha256': source_hash(candidate), 'opponent_sha256': source_hash(baseline),
              'opponent': 'frozen submission package, independent process, seat 1 (not leader)',
              'metric_definitions': {'action_utilization': 'state-changing non-MOVE unit actions / engine unit action calls',
                                     'sw_utilization': 'mean occupied productive-structure tiles /25 at every observation after unlock',
                                     'crop_deaths': 'PLANT to WEED during daily water refresh; lifecycle decay separately counted',
                                     'missed_feeds': 'unfed animal-days immediately before engine daily refresh, after final actions'}, 'games': []}
    output = results / (args.phase + '.json')
    if output.exists():
        saved = json.loads(output.read_text(encoding='utf-8'))
        if (saved['source_sha256'], saved['opponent_sha256']) != (result['source_sha256'], result['opponent_sha256']):
            raise RuntimeError('Source hashes differ from saved benchmark')
        result = saved
    for seed in args.seeds:
        if any(game['seed'] == seed for game in result['games']):
            continue
        game = run_game(make, engine, candidate, baseline, seed)
        result['games'].append(game)
        result['summary'] = {'mean_score': sum(g['score'] for g in result['games'])/len(result['games']), 'worst_score': min(g['score'] for g in result['games'])}
        output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in game.items() if k not in ('daily', 'actions', 'gate_trace')}), flush=True)
    print(json.dumps(result['summary']), flush=True)


if __name__ == '__main__':
    main()
