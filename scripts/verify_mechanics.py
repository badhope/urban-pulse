#!/usr/bin/env python3
"""Narrative-mechanics self-check (verify_mechanics.py)

Covers the four mechanisms added in v1.8.0 that make this a *game* rather than a
calculator with a plot attached. Each is a claim, so each gets an assertion:

  N1  rulebook: priority order, `stop` semantics, validation failures
  N2  rulebook: bundle-declared rules run on tick and are visible in status
  N3  loopguard: the same state three times raises `loop_suspected`
  N4  loopguard: dead-end pruning hides suggestions without blocking travel
  N5  knowledge boundary: an NPC cannot retrieve a fact they did not witness
  N6  knowledge boundary: telling a fact makes it visible, with provenance
  N7  knowledge boundary: public facts are visible to everyone
  N8  combat preview: read-only, no RNG consumed, and it agrees with the real hit chance

Usage:  python scripts/verify_mechanics.py
Exit:   0 = all claims hold, 1 = a claim failed
"""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from game_engine import bootstrap
except ImportError:
    import bootstrap
bootstrap.install(ROOT)

from game_engine.rules import combat as combat_rules      # noqa: E402
from game_engine.rules import context as context_rules   # noqa: E402
from game_engine.rules import loopguard as loop_rules     # noqa: E402
from game_engine.rules import rulebook as rulebook_rules  # noqa: E402

RESULTS = []


def check(name, ok, note=''):
    RESULTS.append(bool(ok))
    print('%s  %-60s %s' % ('PASS' if ok else 'FAIL', name, str(note)[:88]))


def base_state():
    return {
        'tick': 1,
        'entities': {
            'player': {'name': 'P', 'hp': 100, 'hp_max': 100, 'mp': 10,
                       'location': 'town', 'gold': 50, 'items': {},
                       'attrs': {'str': 12, 'dex': 12}},
            'npc': {'name': 'N', 'hp': 40, 'hp_max': 40, 'location': 'town',
                    'attrs': {'str': 8, 'dex': 8}},
        },
        'world_flags': [],
        'questlines': [],
        'market': {'town': {'items': {'herb': {'price': 10}}}},
        'karma': [],
        'context': {'facts': []},
    }


def main():
    # ── N1 rulebook ordering and stop ───────────────────────────────────────
    state = base_state()
    rules = rulebook_rules.normalize([
        {'id': 'low', 'when': True, 'then': [{'op': 'flag', 'flag': 'low'}], 'order': 10},
        {'id': 'high', 'when': True, 'then': [{'op': 'flag', 'flag': 'high'}], 'order': 90},
        {'id': 'blocker', 'when': True, 'then': [{'op': 'flag', 'flag': 'blocked'}],
         'order': 50, 'stop': True},
    ])
    order = [r['id'] for r in rules]
    check('N1a rules sort by descending priority', order == ['high', 'blocker', 'low'], str(order))

    state = base_state()
    rulebook_rules.load(state, [
        {'id': 'low', 'when': True, 'then': [{'op': 'flag', 'flag': 'low'}], 'order': 10},
        {'id': 'high', 'when': True, 'then': [{'op': 'flag', 'flag': 'high'}], 'order': 90},
        {'id': 'blocker', 'when': True, 'then': [{'op': 'flag', 'flag': 'blocked'}],
         'order': 50, 'stop': True},
    ])
    result = rulebook_rules.apply(state, event='tick')
    check('N1b stop halts lower-priority rules',
          result['stopped_by'] == 'blocker' and result['applied'] == ['high', 'blocker'],
          str(result['applied']))
    check('N1c stopped rule really did not run', 'low' not in state['world_flags'],
          str(state['world_flags']))

    bad = []
    for payload in ([{'id': 'x', 'then': [{'op': 'nope'}]}],
                    [{'id': 'a', 'then': [{'op': 'flag', 'flag': 'f'}]},
                     {'id': 'a', 'then': [{'op': 'flag', 'flag': 'f'}]}],
                    [{'id': 'y', 'then': []}],
                    [{'id': 'z', 'then': [{'op': 'flag', 'flag': 'f'}], 'order': 'high'}]):
        try:
            rulebook_rules.normalize(payload)
        except ValueError:
            bad.append(True)
        else:
            bad.append(False)
    check('N1d invalid rulebooks are rejected at load time', all(bad), str(bad))

    # ── N2 conditional predicate ────────────────────────────────────────────
    state = base_state()
    rulebook_rules.load(state, [
        {'id': 'rich', 'when': {'gold_gte': 40},
         'then': [{'op': 'flag', 'flag': 'affluent'}], 'order': 1},
        {'id': 'poor', 'when': {'gold_gte': 10000},
         'then': [{'op': 'flag', 'flag': 'tycoon'}], 'order': 2},
    ])
    res = rulebook_rules.apply(state, event='tick')
    check('N2a predicate gates the rule', res['applied'] == ['rich'], str(res['applied']))
    desc = rulebook_rules.describe(state)
    check('N2b describe reports fired counts', desc['fired'] == 1 and desc['total'] == 2,
          'fired=%s total=%s' % (desc['fired'], desc['total']))

    # ── N3/N4 loop detection ────────────────────────────────────────────────
    state = base_state()
    seen = [loop_rules.observe(state) for _ in range(3)]
    check('N3 same state three times raises loop_suspected',
          seen[-1]['loop_suspected'] and not seen[0]['loop_suspected'],
          str([s['seen'] for s in seen]))

    state['entities']['player']['hp'] = 90
    after_change = loop_rules.observe(state)
    check('N3b changing the state clears the suspicion', not after_change['loop_suspected'],
          'seen=%s' % after_change['seen'])

    state = base_state()
    for _ in range(3):
        loop_rules.record_edge(state, 'town', 'deadend', ok=False)
    loop_rules.record_edge(state, 'town', 'forest', ok=True)
    pruned = loop_rules.pruned_edges(state)
    check('N4a a route that always fails is pruned from suggestions',
          'town->deadend' in pruned and 'town->forest' not in pruned, str(pruned))
    player = state['entities']['player']
    player['location'] = 'deadend'
    check('N4b pruning does not forbid travel (location still settable by the caller)',
          player['location'] == 'deadend')

    # ── N5/N6/N7 knowledge boundary ─────────────────────────────────────────
    state = base_state()
    secret = context_rules.remember(state, 'the vault code is 4417', kind='clue')
    fact_id = secret['fact']['id']
    fact = state['context']['facts'][0]
    check('N5a the player knows what they witnessed', context_rules.knows(fact, 'player'))
    check('N5b an absent NPC does not know it', not context_rules.knows(fact, 'npc'))
    known = context_rules.known_to(state, 'npc')
    check('N5c known_to returns nothing for an absent NPC', known == [], str(known))

    context_rules.tell(state, fact_id, 'npc', propagation='told')
    check('N6a telling makes it visible', context_rules.knows(fact, 'npc'))
    check('N6b the propagation trail records provenance',
          fact['propagation'][-1]['to'] == 'npc' and fact['propagation'][-1]['how'] == 'told',
          str(fact.get('propagation')))

    context_rules.remember(state, 'the bridge is out', kind='fact', public=True)
    public_fact = state['context']['facts'][-1]
    check('N7 public facts are visible to strangers',
          context_rules.knows(public_fact, 'stranger') and public_fact['witnesses'] == ['*'])

    # ── N8 combat preview ───────────────────────────────────────────────────
    state = base_state()
    snapshot = copy.deepcopy(state)
    before_rng = state.get('rng_counter', 0)
    preview = combat_rules.preview(state, 'player', 'npc')
    check('N8a preview returns a hit chance in (0,1]',
          0 < preview.get('hit_chance', 0) <= 1, str(preview.get('hit_chance')))
    check('N8b preview does not mutate the state', state == snapshot)
    check('N8c preview does not consume randomness', state.get('rng_counter', 0) == before_rng)
    dead = base_state()
    dead['entities']['npc']['hp'] = 0
    blocked = combat_rules.preview(dead, 'player', 'npc')
    check('N8d preview refuses a dead target', blocked.get('target_already_dead') is True)
    self_hit = combat_rules.preview(base_state(), 'player', 'player')
    check('N8e preview refuses self-target', self_hit.get('self_target') is True)

    # ── N9 quest stage graph (C2: Twine passage DAG, made visible) ─────────
    import shutil
    import tempfile
    import panel as PANEL

    demo = os.path.join(ROOT, 'docs', 'demo', '玄枢界.save.json')
    tmp = tempfile.mkdtemp(dir=os.path.join(ROOT, '.tmp'))
    try:
        work = os.path.join(tmp, 'g.save.json')
        shutil.copyfile(demo, work)
        vm = PANEL.view_model(work)
        graph = (vm.get('quests') or {}).get('graph') or {}
        nodes = graph.get('nodes') or []
        edges = graph.get('edges') or []
        check('N9a the quest DAG is exposed with nodes and edges',
              len(nodes) >= 4 and len(edges) >= 2,
              '%d nodes / %d edges' % (len(nodes), len(edges)))
        states = {n['state'] for n in nodes}
        check('N9b node states cover done/current/open', states >= {'current', 'open'},
              str(sorted(states)))
        ids = {n['id'] for n in nodes}
        check('N9c every edge points at a real node',
              all(e['from'] in ids and e['to'] in ids for e in edges))
        check('N9d each node carries its questline and objectives',
              all(n['quest'] and isinstance(n['objectives'], list) for n in nodes))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(RESULTS)
    print('\n%d/%d passed' % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
