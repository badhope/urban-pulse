"""Rulebook: setting-declared rules with priority and exceptions.

Why this exists
--------------
World-specific exceptions were hard-coded in `combat.py` / `social.py`. Every
new setting that wanted "in this world, fire damage also scorches armour" had
to change the engine — which directly contradicts the product's central claim:
swap worlds without changing code.

This module gives a bundle a way to declare rules as **data**:

    rule = {
        "id": "xuanshu_fire_scorch",
        "when": {"all": [{"flag": "burning_ground"}, {"tick_gte": 10}]},
        "then": [{"op": "resource", "key": "hp", "delta": -2}],
        "order": 50,          # higher runs first
        "stop": False,        # True = nothing after this rule runs

Design notes
------------
* Predicates are **reused** from `questline.evaluate`, not reimplemented. One
  predicate language for quests, achievements and rules means one place to fix
  a bug and one mental model for bundle authors.
* Effects are **reused** from `systems`, the same restricted whitelist the
  custom subsystem already exposes. A rule can therefore never touch a path the
  engine does not already allow.
* `stop` implements Inform's "instead of" semantics without a new concept:
  ordered rules plus an early exit is enough to express "this overrides that".
* Ordering is stable and total: `(-order, declaration_index)`. Two rules with
  equal order run in declaration order, so results never depend on dict
  iteration order.

Validation is fail-fast at load time: an unknown key in `when`, a non-whitelisted
`then` op, or a non-integer `order` raises with the offending rule id, because a
bundle that silently does nothing is worse than one that refuses to load.
"""

from __future__ import annotations

MAX_RULES = 200
MAX_ORDER = 10000


def _text(value, limit=120) -> str:
    return str(value if value is not None else '').strip()[:limit]


def normalize(raw_rules) -> list:
    """Validate and sort a bundle's `rules` list.

    Returns rules in execution order. Raises ValueError naming the bad rule.
    """
    if raw_rules is None:
        return []
    if not isinstance(raw_rules, (list, tuple)):
        raise ValueError('bundle.rules 必须是列表')

    rules = []
    seen = set()
    for index, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            raise ValueError('rules[%d] 必须是对象' % index)
        rid = _text(raw.get('id'), 60)
        if not rid:
            raise ValueError('rules[%d] 缺少 id' % index)
        if rid in seen:
            raise ValueError('规则 id 重复: %r' % rid)
        seen.add(rid)

        when = raw.get('when', True)
        if not isinstance(when, (dict, bool)):
            raise ValueError('规则 %r 的 when 必须是谓词对象或布尔值' % rid)

        then = raw.get('then')
        if not isinstance(then, list) or not then:
            raise ValueError('规则 %r 的 then 必须是非空效果列表' % rid)
        from game_engine.rules import systems as system_rules
        for effect in then:
            if not isinstance(effect, dict):
                raise ValueError('规则 %r 的 then 含非对象效果' % rid)
            op = _text(effect.get('op'), 20).lower()
            if op not in system_rules.EFFECT_OPS:
                raise ValueError('规则 %r 的效果 op=%r 不在白名单（%s）'
                                 % (rid, op, ' / '.join(system_rules.EFFECT_OPS)))

        try:
            order = int(raw.get('order', 0))
        except (TypeError, ValueError):
            raise ValueError('规则 %r 的 order 必须是整数' % rid) from None
        if not -MAX_ORDER <= order <= MAX_ORDER:
            raise ValueError('规则 %r 的 order 超出范围 ±%d' % (rid, MAX_ORDER))

        rules.append({
            'id': rid,
            'when': when,
            'then': then,
            'order': order,
            'stop': bool(raw.get('stop', False)),
            'note': _text(raw.get('note'), 200),
            '_index': index,
        })

    if len(rules) > MAX_RULES:
        raise ValueError('规则数量 %d 超过上限 %d' % (len(rules), MAX_RULES))

    # Total, stable order: priority first, declaration order as tie-break.
    rules.sort(key=lambda r: (-r['order'], r['_index']))
    for rule in rules:
        rule.pop('_index', None)
    return rules


def index_of(state: dict) -> dict:
    """Return the rulebook stored on the state, normalising lazily."""
    book = state.get('rulebook')
    if not isinstance(book, dict):
        book = {'rules': [], 'fired': {}}
        state['rulebook'] = book
    if not isinstance(book.get('rules'), list):
        book['rules'] = []
    if not isinstance(book.get('fired'), dict):
        book['fired'] = {}
    return book


def load(state: dict, raw_rules) -> dict:
    """Install validated rules onto the state. Returns a summary."""
    rules = normalize(raw_rules)
    book = index_of(state)
    book['rules'] = rules
    book['fired'] = {k: v for k, v in book['fired'].items()
                     if k in {r['id'] for r in rules}}
    return {'rules': len(rules), 'ids': [r['id'] for r in rules]}


def apply(state: dict, event: str = '', extra=None) -> dict:
    """Run the rulebook against the current state.

    `event` is a free-form label (usually the tool name) exposed to predicates as
    `{"event": "..."}` so a bundle can scope a rule to one kind of action.
    """
    from game_engine.rules import questline as quest_rules
    from game_engine.rules import systems as system_rules

    book = index_of(state)
    rules = book['rules']
    if not rules:
        return {'applied': [], 'stopped_by': None, 'rules': 0}

    probe = dict(state)
    if event:
        probe['_event'] = event
    if isinstance(extra, dict):
        probe.update(extra)

    applied = []
    stopped_by = None
    for rule in rules:
        if not quest_rules.evaluate(probe, rule['when']):
            continue
        effects = []
        for effect in rule['then']:
            try:
                effects.append(system_rules._apply_effect(state, effect))
            except (ValueError, KeyError, TypeError) as exc:
                # A rule that cannot apply is reported, not silently dropped:
                # a bundle author must be able to see why nothing happened.
                effects.append({'error': str(exc)[:160]})
        applied.append({'id': rule['id'], 'effects': effects})
        book['fired'][rule['id']] = int(book['fired'].get(rule['id'], 0) or 0) + 1
        if rule['stop']:
            stopped_by = rule['id']
            break

    return {'applied': [a['id'] for a in applied],
            'effects': applied,
            'stopped_by': stopped_by,
            'rules': len(rules)}


def describe(state: dict) -> dict:
    """Read-only view for the panel and for `status`."""
    book = index_of(state)
    rules = book['rules']
    fired = book['fired']
    return {
        'total': len(rules),
        'fired': sum(1 for r in rules if fired.get(r['id'])),
        'rules': [{
            'id': r['id'],
            'order': r['order'],
            'stop': r['stop'],
            'note': r.get('note', ''),
            'fired': int(fired.get(r['id'], 0) or 0),
            'effects': len(r['then']),
        } for r in rules],
    }
