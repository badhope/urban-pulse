#!/usr/bin/env python3
"""
体系与模板自检 (verify_systems.py)

为什么需要：v1.4 引入七类数据驱动体系（时间/掉落/制造/声望/成就/成长/自定义）与
八套游戏模板。它们最容易犯的错是"配了但不生效"或"模板缺件却能被开局"。
本脚本把两件事钉成断言：
  · 每类体系的**行为**（推进、掉落确定性、制造成功率、声望分档、成就只发一次、
    成长曲线与属性成长、自定义动作的受限效果）
  · 每套模板的**完整性**（validate 无问题、能 build_state、能跑体系动作、引用完整）

覆盖：
  S1 时间体系：推进/跨天/季节/天气/有界日志/确定性
  S2 掉落体系：权重抽样确定性、grant 入库、空表/未知表、数量区间
  S3 制造体系：材料校验、成功产出、失败返还、概率随属性
  S4 声望体系：clamp、分档、未知势力自动建档、上限
  S5 成就体系：条件求值、只解锁一次、奖励发放
  S6 成长体系：XP 曲线、跨级、属性成长、等级上限
  S7 自定义体系：白名单效果、计数、未知动作拒绝
  S8 模板库：8 套全量 validate + build_state + 体系可执行 + 覆盖合并
  S9 MCP 集成：template_start/system_run/system_status/system_define 端到端
  S10 面板：/state.systems 区块

用法:  python scripts/verify_systems.py
退出码: 0 = 全绿；1 = 有失败
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if 'game_engine' not in sys.modules:
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        'game_engine', os.path.join(ROOT, '__init__.py'),
        submodule_search_locations=[ROOT])
    _pkg = importlib.util.module_from_spec(_spec)
    _pkg.__path__ = [ROOT]
    sys.modules['game_engine'] = _pkg
    _spec.loader.exec_module(_pkg)

import templates as TPL                              # noqa: E402
from game_engine import settings_loader as SL        # noqa: E402
from game_engine.rules import gamesystem as GS       # noqa: E402
from game_engine.rules import systems as SYS         # noqa: E402
from game_engine.state_schema import save_state, load_state  # noqa: E402

RESULTS = []
STRICT_FAILURES = []


def check(name, got, want, tol=1e-9):
    ok = False
    try:
        if isinstance(want, (int, float)) and isinstance(got, (int, float)) \
                and not isinstance(want, bool) and not isinstance(got, bool):
            ok = abs(float(got) - float(want)) <= tol * max(1.0, abs(float(want)))
        else:
            ok = got == want
    except Exception:
        ok = False
    RESULTS.append(bool(ok))
    print('%s  %-56s got=%s want=%s' % ('PASS' if ok else 'FAIL', name, got, want))


def check_true(name, cond, note=''):
    RESULTS.append(bool(cond))
    print('%s  %-56s %s' % ('PASS' if cond else 'FAIL', name, str(note)[:70]))


def check_raises(name, fn, exc=ValueError):
    try:
        fn()
    except exc:
        RESULTS.append(True)
        print('PASS  %-56s raises %s' % (name, exc.__name__))
        return
    except Exception as e:
        RESULTS.append(False)
        print('FAIL  %-56s raised %s（期望 %s）' % (name, type(e).__name__, exc.__name__))
        return
    RESULTS.append(False)
    print('FAIL  %-56s 未抛异常' % name)


def base_state(**extra):
    st = {
        'tick': 7, 'rng_seed': 42, 'rng_counter': 0, 'config': {},
        'entities': {'player': {'name': '甲', 'hp': 20, 'hp_max': 20, 'mp': 5, 'mp_max': 10,
                                'gold': 100, 'items': {'herb': 4}, 'attrs': {'str': 10, 'int': 14}}},
        'relations': {}, 'event_log': [], 'karma_ledger': [], 'world_flags': [],
        'market': {}, 'world_info': {'name': '测试'},
    }
    st.update(extra)
    return st


# ── S1 时间体系 ────────────────────────────────────────────
def s1_time():
    st = base_state()
    SYS.define(st, {'id': 'clock', 'kind': 'time',
                    'config': {'start': {'day': 1, 'hour': 9, 'minute': 30},
                               'days_per_season': 2}})
    out = SYS.run(st, 'clock', 'advance', {'minutes': 60})
    check('S1 推进 60 分钟后 hour', out['hour'], 10)
    check('S1 clock 格式', out['clock'], '10:30')

    out2 = SYS.run(st, 'clock', 'advance', {'minutes': 24 * 60})
    check('S1 跨天后 day', out2['day'], 2)
    check('S1 跨天后 hour 值', out2['hour'], 10)

    out3 = SYS.run(st, 'clock', 'advance', {'minutes': 2 * 24 * 60})
    check('S1 跨季节后 season 变化', out3['season_changed'], True)
    check('S1 seasons 按 days_per_season 轮转（第 4 天 → 第二季）', out3['season'], '夏')

    rt = st['systems']['rt']['clock']
    check_true('S1 时间日志有界（≤ log_cap）', len(rt['log']) <= 100, '%d 条' % len(rt['log']))

    # 确定性：同 state 同参数两次推进结果一致
    a, b = base_state(), base_state()
    for s in (a, b):
        SYS.define(s, {'id': 'c', 'kind': 'time',
                       'config': {'start': {'day': 1, 'hour': 0}, 'days_per_season': 3}})
    ra = SYS.run(a, 'c', 'advance', {'minutes': 3 * 24 * 60})
    rb = SYS.run(b, 'c', 'advance', {'minutes': 3 * 24 * 60})
    check('S1 同种子同参数时间推进输出', ra, rb)

    check_raises('S1 minutes=0 被拒绝', lambda: SYS.run(st, 'clock', 'advance', {'minutes': 0}))
    check_raises('S1 未知动作被拒绝', lambda: SYS.run(st, 'clock', 'jump', {}))


# ── S2 掉落体系 ────────────────────────────────────────────
def s2_loot():
    st = base_state()
    SYS.define(st, {'id': 'drops', 'kind': 'loot', 'config': {'tables': {
        'mob': {'rolls': 3, 'entries': [
            {'item': 'a', 'name': 'A', 'weight': 100, 'qty': [1, 1]},
        ]},
        'rare': {'rolls': 2, 'empty_weight': 0, 'entries': [
            {'item': 'x', 'name': 'X', 'weight': 1, 'qty': [1, 1]},
            {'item': 'y', 'name': 'Y', 'weight': 1, 'qty': [1, 1]},
        ]},
    }}})

    out = SYS.run(st, 'drops', 'roll', {'table': 'mob', 'times': 2})
    check('S2 rolls×times = 掉落总数', out['total_qty'], 6)
    check('S2 单条目合并', len(out['drops']), 1)

    a, b = base_state(), base_state()
    for s in (a, b):
        SYS.define(s, {'id': 'd', 'kind': 'loot', 'config': {'tables': {'t': {
            'rolls': 2, 'entries': [
                {'item': 'p', 'name': 'P', 'weight': 50, 'qty': [1, 1]},
                {'item': 'q', 'name': 'Q', 'weight': 50, 'qty': [1, 1]},
            ]}}}})
    check('S2 同种子同 tick 的掉落条目',
          SYS.run(a, 'd', 'roll', {'table': 't'})['drops'],
          SYS.run(b, 'd', 'roll', {'table': 't'})['drops'])

    # 两次不同 tick 应当能出现不同组合（概率性，但 20 次内几乎必然）
    seen = set()
    for i in range(20):
        st['tick'] = i
        drops = SYS.run(st, 'drops', 'roll', {'table': 'rare'})['drops']
        seen.add(tuple(d['item'] for d in drops))
    check_true('S2 掉落随 tick 变化（非恒定）', len(seen) > 1, str(sorted(seen)[:4]))

    granted = SYS.run(st, 'drops', 'roll', {'table': 'mob', 'times': 1, 'grant': True})
    check('S2 grant 写入随身物品', st['entities']['player']['items']['a'], 3)
    check('S2 grant 标记', granted['granted'], True)

    check_raises('S2 未知掉落表被拒绝',
                 lambda: SYS.run(st, 'drops', 'roll', {'table': 'nope'}))
    check_raises('S2 未知动作被拒绝', lambda: SYS.run(st, 'drops', 'drop', {}))


# ── S3 制造体系 ────────────────────────────────────────────
def s3_craft():
    st = base_state()
    SYS.define(st, {'id': 'craft', 'kind': 'craft', 'config': {'recipes': [
        {'id': 'potion', 'name': '药水', 'inputs': {'herb': 2},
         'output': {'item': 'potion', 'name': '药水', 'qty': 1},
         'difficulty': 10, 'attribute': 'int', 'fail_consume': 0.5},
    ]}})

    out = SYS.run(st, 'craft', 'craft', {'recipe': 'potion'})
    check_true('S3 制造返回 success 字段', 'success' in out, str(out.get('success')))
    herb_left = st['entities']['player']['items'].get('herb', 0)
    check('S3 成功扣 2 份材料（剩 2）', herb_left, 2)
    if out['success']:
        check('S3 成功产出药水', st['entities']['player']['items'].get('potion'), 1)
    else:
        check('S3 失败返还一半材料（剩 3）', herb_left, 3)

    # 材料不足
    st2 = base_state()
    st2['entities']['player']['items'] = {'herb': 1}
    SYS.define(st2, {'id': 'craft', 'kind': 'craft', 'config': {'recipes': [
        {'id': 'potion', 'inputs': {'herb': 2}, 'output': {'item': 'potion', 'qty': 1}}]}})
    r2 = SYS.run(st2, 'craft', 'craft', {'recipe': 'potion'})
    check('S3 材料不足时 success=False', r2['success'], False)
    check('S3 材料不足不改动库存', st2['entities']['player']['items']['herb'], 1)

    # 高属性应显著提高成功率
    def rate(attr_value, rounds=60):
        ok = 0
        for i in range(rounds):
            s = base_state()
            s['entities']['player']['items'] = {'herb': 2}
            s['entities']['player']['attrs'] = {'int': attr_value}
            s['tick'] = i
            SYS.define(s, {'id': 'c', 'kind': 'craft', 'config': {'recipes': [
                {'id': 'p', 'inputs': {'herb': 2}, 'output': {'item': 'p', 'qty': 1},
                 'difficulty': 20, 'attribute': 'int'}]}})
            if SYS.run(s, 'c', 'craft', {'recipe': 'p'})['success']:
                ok += 1
        return ok / rounds
    low, high = rate(0), rate(40)
    check_true('S3 属性高时制造成功率更高', high > low + 0.3, 'low=%.2f high=%.2f' % (low, high))

    check_raises('S3 未知配方被拒绝', lambda: SYS.run(st, 'craft', 'craft', {'recipe': 'nope'}))


# ── S4 声望体系 ────────────────────────────────────────────
def s4_reputation():
    st = base_state()
    SYS.define(st, {'id': 'rep', 'kind': 'reputation', 'config': {
        'factions': ['guild', 'temple'],
        'tiers': [{'min': -1000, 'label': '敌对'}, {'min': 0, 'label': '中立'},
                  {'min': 50, 'label': '友好'}, {'min': 90, 'label': '敬重'}],
        'default': 0}})

    up = SYS.run(st, 'rep', 'adjust', {'faction': 'guild', 'delta': 60})
    check('S4 声望增加', up['after'], 60)
    check('S4 分档正确（60 → 友好）', up['tier'], '友好')

    capped = SYS.run(st, 'rep', 'adjust', {'faction': 'guild', 'delta': 100})
    check('S4 上限 clamp 到 100', capped['after'], 100)
    down = SYS.run(st, 'rep', 'adjust', {'faction': 'guild', 'delta': -500})
    check('S4 下限 clamp 到 -100', down['after'], -100)
    check('S4 负值分档（敌对）', down['tier'], '敌对')

    auto = SYS.run(st, 'rep', 'adjust', {'faction': 'new_faction', 'delta': 10})
    check('S4 未知势力自动建档', auto['after'], 10)

    status = SYS.run(st, 'rep', 'status')
    check('S4 status 返回全部势力', sorted(status['factions']), ['guild', 'new_faction', 'temple'])


# ── S5 成就体系 ────────────────────────────────────────────
def s5_achievement():
    st = base_state()
    SYS.define(st, {'id': 'ach', 'kind': 'achievement', 'config': {'items': [
        {'id': 'rich', 'name': '小富', 'condition': {'gold_gte': 50},
         'reward': {'gold': 100, 'xp': 0, 'flags': ['got_rich']}},
        {'id': 'poor', 'name': '清贫', 'condition': {'gold_gte': 100000}, 'reward': {}},
    ]}})

    out = SYS.run(st, 'ach', 'check')
    check('S5 满足条件的成就解锁', [a['id'] for a in out['newly_unlocked']], ['rich'])
    check('S5 奖励金币已发放', st['entities']['player']['gold'], 200)
    check('S5 奖励 flag 已写入', 'got_rich' in st['world_flags'], True)

    again = SYS.run(st, 'ach', 'check')
    check('S5 重复 check 不再重复发奖', again['newly_unlocked'], [])
    check('S5 金币没有二次增加', st['entities']['player']['gold'], 200)

    listed = SYS.run(st, 'ach', 'list')
    check('S5 list 报告解锁状态', (listed['unlocked'], listed['total']), (1, 2))


# ── S6 成长体系 ────────────────────────────────────────────
def s6_progression():
    st = base_state()
    SYS.define(st, {'id': 'xp', 'kind': 'progression', 'config': {
        'base_xp': 100, 'growth': 2.0, 'max_level': 4,
        'per_level': {'str': 2, 'con': 1}, 'level_label': '等级'}})

    check('S6 1 级所需 XP', SYS.need_for_level(st['systems']['defs']['xp'], 1), 100)
    check('S6 2 级所需 XP', SYS.need_for_level(st['systems']['defs']['xp'], 2), 200)

    out = SYS.run(st, 'xp', 'grant', {'amount': 100})
    check('S6 恰好升级一次', (out['level'], out['levels_gained']), (2, [2]))
    check('S6 升级后属性成长', st['entities']['player']['attrs'].get('str'), 12)
    check('S6 stage 同步累加', st['entities']['player'].get('stage'), 1)

    big = SYS.run(st, 'xp', 'grant', {'amount': 10000})
    check('S6 连升不越过 max_level', big['level'], 4)
    cap = SYS.run(st, 'xp', 'grant', {'amount': 10000})
    check('S6 满级后不再升级', cap['levels_gained'], [])

    status = SYS.run(st, 'xp', 'status')
    check('S6 status 含 need 与 max_level', (status['need'] > 0, status['max_level']), (True, 4))


# ── S7 自定义体系 ─────────────────────────────────────────
def s7_custom():
    st = base_state()
    GS.set_profile(st, {'resources': [{'key': 'hp', 'label': '生命', 'value': 10, 'min': 0, 'max': 20}],
                        'attributes': [{'key': 'str', 'label': '力量', 'value': 5}],
                        'meters': [{'key': 'prog', 'label': '进度', 'value': 0, 'min': 0, 'max': 5}]})
    SYS.define(st, {'id': 'acts', 'kind': 'custom', 'config': {'actions': {
        'rest': {'label': '休息', 'effects': [
            {'op': 'resource', 'key': 'hp', 'delta': 5},
            {'op': 'flag', 'flag': 'rested'}]},
        'train': {'label': '训练', 'effects': [
            {'op': 'attribute', 'key': 'str', 'delta': 1},
            {'op': 'meter', 'key': 'prog', 'delta': 2}]},
        'note': {'label': '记录', 'effects': [
            {'op': 'fact', 'text': '今天休息了', 'fact_kind': 'note', 'keys': ['休息']}]},
    }}})

    out = SYS.run(st, 'acts', 'rest')
    check('S7 resource 效果生效', out['effects'][0]['after'], 15)
    check('S7 flag 效果生效', 'rested' in st['world_flags'], True)
    check('S7 动作计数', out['count'], 1)

    train = SYS.run(st, 'acts', 'train')
    check('S7 attribute 效果（5→6）', train['effects'][0]['after'], 6)
    check('S7 meter 效果（0→2）', train['effects'][1]['after'], 2)

    SYS.run(st, 'acts', 'note')
    check('S7 fact 效果写入上下文台账', len(st['context']['facts']), 1)

    check_raises('S7 未知动作被拒绝', lambda: SYS.run(st, 'acts', 'fly'))
    check_raises('S7 非法效果 op 在定义期被拒绝', lambda: SYS.define(st, {
        'id': 'bad', 'kind': 'custom',
        'config': {'actions': {'x': {'effects': [{'op': 'exec', 'cmd': 'rm -rf /'}]}}}}))


# ── S8 模板库 ─────────────────────────────────────────────
def _safe_normalize(system):
    try:
        SYS.normalize_system(system)
        return True
    except Exception:
        return False


def _safe_questlines(QL, questlines):
    try:
        QL.normalize_all(questlines)
        return True
    except Exception:
        return False


def s8_templates():
    rows = TPL.list_templates()
    check_true('S8 模板数量 ≥ 8', len(rows) >= 8, '%d 套' % len(rows))
    check('S8 模板 id 唯一', len({r['id'] for r in rows}), len(rows))

    for row in rows:
        tid = row['id']
        tpl = TPL.get(tid)
        problems = TPL.validate(tpl)
        check('S8 模板 %s 结构完整' % tid, problems, [])
        bundle = TPL.to_bundle(tid)
        st = SL.build_state(bundle)
        SL.apply_runtime_fields(st, bundle)
        ok_min = (len(st['entities']) >= 2 and len(st['market']) >= 1
                  and len(st.get('places') or {}) >= 3
                  and len(st.get('lore') or []) >= 1
                  and len(st.get('questlines') or []) >= 1)
        check_true('S8 模板 %s 可建局（实体/市场/地点/世界书/事业线）' % tid, ok_min,
                   'entities=%d market=%d places=%d lore=%d quests=%d'
                   % (len(st['entities']), len(st['market']), len(st.get('places') or {}),
                      len(st.get('lore') or []), len(st.get('questlines') or [])))
        check('S8 模板 %s 体系已落盘' % tid,
              len((st.get('systems') or {}).get('defs') or {}), len(bundle['systems']))
        check('S8 模板 %s 游戏档案已落盘' % tid,
              (st.get('game') or {}).get('kind'), bundle['game']['kind'])
        # 每套至少有一个体系能执行 status
        first = bundle['systems'][0]['id']
        status = SYS.run(st, first, 'status')
        check_true('S8 模板 %s 首个体系 status 非空' % tid, bool(status), str(status)[:40])

    # 每套模板的 systems / questlines / playbook 都必须能被引擎规范化（不留"看起来有但非法"的配置）
    from game_engine.rules import questline as QL
    from game_engine.rules import playbook as PB
    for row in rows:
        tid = row['id']
        tpl = TPL.get(tid)
        check('S8 模板 %s 的体系定义全部合法' % tid,
              [s2.get('id') for s2 in tpl['systems']
               if _safe_normalize(s2)], [s2.get('id') for s2 in tpl['systems']])
        check_true('S8 模板 %s 的事业线可规范化' % tid,
                   _safe_questlines(QL, tpl['questlines']), tid)
        pb, notes = PB.normalize(tpl['playbook'])
        check('S8 模板 %s 的 playbook 无回退告警' % tid, notes, [])

    # 覆盖合并：深合并 dict、列表整体替换
    base = TPL.get('jrpg')
    merged = TPL.apply_overrides(base, {'world': {'name': '新世界'}, 'player': {'gold': 999}})
    check('S8 overrides 深合并保留其他字段', merged['world']['era'], base['world']['era'])
    check('S8 overrides 覆盖指定字段', merged['world']['name'], '新世界')
    check('S8 overrides 不污染原模板', base['world']['name'] != '新世界', True)
    replaced = TPL.apply_overrides(base, {'level_tiers': ['一', '二']})
    check('S8 overrides 列表整体替换', replaced['level_tiers'], ['一', '二'])

    check_raises('S8 未知模板被拒绝', lambda: TPL.get('nope'))
    # validate 能发现缺件
    broken = TPL.get('jrpg')
    broken['market'] = []
    check_true('S8 validate 能发现缺市场', bool(TPL.validate(broken)), str(TPL.validate(broken)[:2]))


# ── S8b 计数器驱动成就（模板成就不能是死条件）─────────────
def s8b_counters():
    from game_engine.state_schema import bump
    st = base_state()
    check('S8b bump 初始累加', bump(st, 'locations'), 1)
    check('S8b bump 继续累加', bump(st, 'locations', 2), 3)
    check('S8b counters 落盘字段', st['counters'], {'locations': 3})
    bad = base_state()
    bad['counters'] = 'not-a-dict'
    check('S8b 脏 counters 自动重建', bump(bad, 'x'), 1)
    check('S8b 脏 counters 重置为对象', bad['counters'], {'x': 1})
    # 模板成就用 counter_gte，必须能真的被触发
    for tid, key, n in (('jrpg', 'locations', 3), ('mystery', 'clues', 1)):
        tpl = TPL.get(tid)
        achievements = [s2 for s2 in (tpl.get('systems') or []) if s2['kind'] == 'achievement']
        conds = [a['condition'] for a in achievements[0]['config']['items']]
        has_counter = any(isinstance(c, dict) and 'counter_gte' in c for c in conds)
        check_true('S8b 模板 %s 至少一个成就用 counter_gte' % tid, has_counter, str(conds)[:60])
        bundle = TPL.to_bundle(tid)
        st2 = SL.build_state(bundle)
        SL.apply_runtime_fields(st2, bundle)
        bump(st2, key, n)
        system = next(x for x in st2['systems']['defs'].values() if x['kind'] == 'achievement')
        out = SYS.run(st2, system['id'], 'check')
        check_true('S8b 模板 %s 成就随计数器解锁' % tid, out['unlocked'] >= 1, str(out['newly_unlocked']))


# ── S9 MCP 集成 ──────────────────────────────────────────
def s9_mcp():
    try:
        import game_engine.mcp_server as MS
    except Exception as exc:  # aqg: top-level boundary —— 可选 MCP 依赖在 core 路径允许缺失
        message = 'S9 需要 mcp SDK：%s' % str(exc)[:60]
        if os.environ.get('WORLD_GAMES_STRICT') == '1':
            RESULTS.append(False)
            STRICT_FAILURES.append(message)
            print('FAIL  %s' % message)
        else:
            print('SKIP  %s' % message)
        return
    import game_engine.panel as PANEL

    tmp = tempfile.mkdtemp(prefix='ww-sys-int-')
    old_env = os.environ.get('WORLD_GAMES_SAVES')
    old_path = MS._active.get('path')
    os.environ['WORLD_GAMES_SAVES'] = os.path.join(tmp, 'saves')
    try:
        started = MS.template_start('mystery', name='体系集成测试')
        check('S9 template_start 建局', started['name'], '体系集成测试')
        check('S9 模板体系已载入', len(started['systems']), 5)

        listed = MS.system_status()
        check('S9 system_status 列出全部体系', len(listed['systems']), 5)

        one = MS.system_status('clock')
        check('S9 system_status 单个体系带 config/runtime',
              ('config' in one, 'runtime' in one), (True, True))

        adv = MS.system_run('clock', 'advance', {'minutes': 120})
        check('S9 system_run 推进时间', adv['hour'], 22)

        rep = MS.system_run('trust', 'adjust', {'faction': '巡捕房', 'delta': 30})
        check('S9 system_run 声望', rep['after'], 30)

        defined = MS.system_define({'id': 'extra', 'kind': 'custom',
                                    'config': {'actions': {'wave': {'label': '招手', 'effects': []}}}})
        check('S9 system_define 新增体系', defined['system']['id'], 'extra')
        check('S9 新增后总数', defined['total'], 6)

        ran = MS.system_run('extra', 'wave')
        check('S9 新体系动作可执行', ran['action'], 'wave')

        removed = MS.system_remove('extra')
        check('S9 system_remove 移除', (removed['removed'], removed['total']), (True, 5))

        schema = MS.system_schema()
        check('S9 system_schema 覆盖 7 类体系', len(schema['kinds']), 7)
        check('S9 system_schema 有模板字段清单', len(schema['template_fields']) >= 15, True)

        bundle_res = MS.template_apply('tabletop', overrides={'world': {'name': '自定世界'}})
        check('S9 template_apply 不落盘且可覆盖',
              bundle_res['bundle']['world']['name'], '自定世界')

        vm = PANEL.view_model(MS._state_path())
        check('S9 面板视图带 systems 区块', sorted(vm['systems'].keys()),
              ['kinds', 'rows', 'total'])
        check('S9 面板能读到体系行', len(vm['systems']['rows']) >= 5, True)
    finally:
        MS._active['path'] = old_path
        if old_env is None:
            os.environ.pop('WORLD_GAMES_SAVES', None)
        else:
            os.environ['WORLD_GAMES_SAVES'] = old_env


# ── S10 有界性与确定性 ───────────────────────────────────
def s10_bounds():
    st = base_state()
    for i in range(SYS.MAX_DEFS):
        SYS.define(st, {'id': 's%d' % i, 'kind': 'custom', 'config': {'actions': {}}})
    check('S10 体系数量上限', len(st['systems']['defs']), SYS.MAX_DEFS)
    check_raises('S10 超出上限被拒绝', lambda: SYS.define(st, {
        'id': 'overflow', 'kind': 'custom', 'config': {'actions': {}}}))

    check_raises('S10 未知 kind 被拒绝', lambda: SYS.normalize_system({'id': 'x', 'kind': 'magic'}))
    check_raises('S10 缺 id 被拒绝', lambda: SYS.normalize_system({'kind': 'time'}))

    # 脏配置：错误类型不崩，回退默认
    norm = SYS.normalize_system({'id': 't', 'kind': 'time', 'config': {'seasons': 'not-a-list',
                                                                      'days_per_season': 'x'}})
    check('S10 脏配置回退默认季节', norm['config']['seasons'], list(SYS.DEFAULT_SEASONS))
    check('S10 脏配置回退默认天数', norm['config']['days_per_season'], 30)

    # 快照回退：体系运行态随状态一起回退
    st2 = base_state()
    SYS.define(st2, {'id': 'c', 'kind': 'time', 'config': {'start': {'day': 1, 'hour': 0}}})
    SYS.run(st2, 'c', 'advance', {'minutes': 600})
    tmp = tempfile.mkdtemp(prefix='ww-sys-snap-')
    p = os.path.join(tmp, 's.json')
    save_state(st2, p)
    loaded = load_state(p)
    check('S10 体系运行态随存档落盘', loaded['systems']['rt']['c']['hour'], 10)

    # 旧的 4 套设定包不受影响
    for name in ('玄枢界', '折剑行', '霓虹深渊', '雾港'):
        with open(os.path.join(ROOT, 'settings', '%s.setting.json' % name), encoding='utf-8') as f:
            bundle = json.load(f)
        st3 = SL.build_state(bundle)
        SL.apply_runtime_fields(st3, bundle)
        check('S10 旧设定包 %s 仍可载入（无 systems 也不报错）' % name,
              (len(st3['entities']) > 0, 'systems' not in st3 or isinstance(st3['systems'], dict)),
              (True, True))


def main():
    print('── S1 时间体系 ──')
    s1_time()
    print('\n── S2 掉落体系 ──')
    s2_loot()
    print('\n── S3 制造体系 ──')
    s3_craft()
    print('\n── S4 声望体系 ──')
    s4_reputation()
    print('\n── S5 成就体系 ──')
    s5_achievement()
    print('\n── S6 成长体系 ──')
    s6_progression()
    print('\n── S7 自定义体系 ──')
    s7_custom()
    print('\n── S8 模板库 ──')
    s8_templates()
    print('\n── S8b 计数器驱动成就 ──')
    s8b_counters()
    print('\n── S9 MCP 集成 ──')
    s9_mcp()
    print('\n── S10 有界性/确定性 ──')
    s10_bounds()

    passed = sum(RESULTS)
    print('\n%d/%d passed' % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) and not STRICT_FAILURES else 1


if __name__ == '__main__':
    sys.exit(main())
